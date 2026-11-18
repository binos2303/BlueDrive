"""Recovery must converge with publication and fence reclaimed worker results."""
import io
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from files.finalization import finalize_verified_upload
from files.models import File, FileVersion, QuotaReservation, StorageConfig, StorageLocation, UploadFinalizationJob, UploadSession
from files.storage_adapters.base import StorageIntegrityError, StorageNotFoundError, StorageRetryableError
from files.tests.test_finalization_permissions import FinalizationFixture


@contextmanager
def fail_fileversion_commit(*, deleting=False):
    # Constraint trigger lỗi khi PostgreSQL COMMIT, sau các ORM writes.
    operation = "DELETE" if deleting else "INSERT"
    with connection.cursor() as cursor:
        cursor.execute(f"""
                CREATE FUNCTION p5_fail_publication_commit() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'P5 test commit rollback' USING ERRCODE = '40001';
                END $$;
                CREATE CONSTRAINT TRIGGER p5_fail_publication_commit
                AFTER {operation} ON files_fileversion DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW EXECUTE FUNCTION p5_fail_publication_commit()
        """)
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TRIGGER p5_fail_publication_commit ON files_fileversion")
            cursor.execute("DROP FUNCTION p5_fail_publication_commit()")


@override_settings(SECUREDRIVE_UPLOAD_SCANNER="")
class FinalizationCommitTests(FinalizationFixture, TransactionTestCase):
    serialized_rollback = True

    def test_deferred_serialization_failure_preserves_staging_and_retries(self):
        with fail_fileversion_commit():
            with self.assertLogs("files.management.commands.finalize_uploads", level="ERROR"):
                call_command("finalize_uploads", stdout=io.StringIO())
        self.upload.refresh_from_db()
        job = UploadFinalizationJob.objects.get(upload_session=self.upload)
        self.assertEqual((self.upload.state, job.state, job.attempts), ("verifying", "pending", 1))
        self.assertIsNone(self.upload.file_id)
        self.assertFalse(File.objects.filter(workspace=self.workspace).exists())
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "reserved")
        self.adapter.delete_object.assert_not_called()
        self.adapter.quarantine_object.assert_not_called()
        call_command("finalize_uploads", stdout=io.StringIO())
        job.refresh_from_db()
        self.upload.refresh_from_db()
        self.assertEqual((job.state, job.attempts, self.upload.state), ("done", 2, "available"))
        self.assertEqual(File.objects.filter(workspace=self.workspace).count(), 1)
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "consumed")


@override_settings(SECUREDRIVE_UPLOAD_SCANNER="")
class FinalizationRecoveryTests(FinalizationFixture, TestCase):
    def test_expired_cleanup_retains_receipt_and_skips_referenced_object(self):
        unrelated = File.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner, file_name="retained.txt",
        )
        version = FileVersion.objects.create(
            tenant=self.tenant, file=unrelated, version_number=1, state="deleting", size_bytes=1,
        )
        StorageLocation.objects.create(
            tenant=self.tenant, file_version=version,
            storage_config=StorageConfig.objects.create(tenant=self.tenant, provider="s3"),
            object_ref=self.upload.object_key, state="error",
        )
        UploadSession.objects.filter(pk=self.upload.pk).update(state="failed", expires_at=timezone.now())
        with patch("files.management.commands.cleanup_uploads.get_storage_adapter", return_value=self.adapter):
            out = io.StringIO()
            call_command("cleanup_uploads", stdout=out)
        self.assertIn("cleanup pending: 1", out.getvalue())
        self.adapter.abort_multipart.assert_not_called()
        self.adapter.delete_object.assert_not_called()
        current = UploadSession.objects.get(pk=self.upload.pk)
        self.assertEqual(current.object_key, self.upload.object_key)
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "released")

    def test_failed_quarantine_receipt_is_recoverable_after_retryable_cleanup(self):
        staging_key = self.upload.object_key
        quarantine_key = f"quarantine/{self.upload.pk.hex}"
        UploadSession.objects.filter(pk=self.upload.pk).update(state="failed", expires_at=timezone.now())
        self.adapter.delete_object.side_effect = StorageRetryableError("Fixture timeout")
        with patch("files.management.commands.cleanup_uploads.get_storage_adapter", return_value=self.adapter):
            call_command("cleanup_uploads", stdout=io.StringIO())
            self.upload.refresh_from_db()
            self.assertEqual(self.upload.object_key, staging_key)
            self.adapter.delete_object.side_effect = None
            self.adapter.delete_object.reset_mock()
            call_command("cleanup_uploads", stdout=io.StringIO())
            self.adapter.delete_object.assert_any_call(staging_key)
            self.adapter.delete_object.assert_any_call(quarantine_key)
        self.upload.refresh_from_db()
        self.assertEqual((self.upload.object_key, self.upload.provider_upload_id), ("", ""))
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "released")

    def test_reclaim_after_third_crash_does_not_start_fourth_attempt(self):
        UploadFinalizationJob.objects.filter(upload_session=self.upload).update(
            state="processing", attempts=3, updated_at=timezone.now() - timedelta(minutes=11),
        )
        call_command("finalize_uploads", stdout=io.StringIO())
        self.adapter.complete_multipart.assert_not_called()
        job = UploadFinalizationJob.objects.get(upload_session=self.upload)
        self.upload.refresh_from_db()
        self.assertEqual((job.state, job.attempts, self.upload.state), ("failed", 3, "failed"))
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "released")

    def test_crash_after_publication_recovers_done_without_touching_storage(self):
        result = finalize_verified_upload(self.upload, self.payload, self.editor)
        job = UploadFinalizationJob.objects.get(upload_session=self.upload)
        UploadFinalizationJob.objects.filter(pk=job.pk).update(
            state="processing", attempts=1, updated_at=timezone.now() - timedelta(minutes=11),
        )
        self.adapter.reset_mock()
        self.adapter.complete_multipart.side_effect = StorageNotFoundError("Staging already deleted")
        call_command("finalize_uploads", stdout=io.StringIO())
        job.refresh_from_db()
        self.upload.refresh_from_db()
        self.assertEqual((job.state, job.attempts), ("done", 1))
        self.assertEqual(self.upload.state, "available")
        self.assertEqual(self.upload.file_id, result["file_id"])
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "consumed")
        self.assertEqual(self.adapter.mock_calls, [])

    def test_terminal_failure_does_not_repeat_storage_or_reserve_quota(self):
        UploadSession.objects.filter(pk=self.upload.pk).update(state="failed")
        # A terminal upload needs no network work, even when its job remained pending.
        call_command("finalize_uploads", stdout=io.StringIO())
        self.assertEqual(UploadFinalizationJob.objects.get(upload_session=self.upload).state, "failed")
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "released")
        self.adapter.complete_multipart.assert_not_called()

    def reclaim(self):
        UploadFinalizationJob.objects.filter(upload_session=self.upload).update(
            attempts=2, state="processing", updated_at=timezone.now(),
        )

    def test_reclaimed_worker_cannot_publish_or_change_new_claim(self):
        published = self.adapter.publish_verified_object.return_value

        def copy(*args, **kwargs):
            self.reclaim()
            return published

        self.adapter.publish_verified_object.side_effect = copy
        call_command("finalize_uploads", stdout=io.StringIO())
        self.upload.refresh_from_db()
        job = UploadFinalizationJob.objects.get(upload_session=self.upload)
        self.assertEqual((job.state, job.attempts), ("processing", 2))
        self.assertEqual(self.upload.state, "verifying")
        self.assertFalse(File.objects.filter(workspace=self.workspace).exists())
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "reserved")
        self.adapter.delete_object.assert_not_called()
        self.adapter.quarantine_object.assert_not_called()

    def test_reclaimed_worker_error_cannot_fail_new_claim_or_release_quota(self):
        def download(*args, **kwargs):
            self.reclaim()
            raise StorageIntegrityError("Old worker failed after new claim")

        self.adapter.download_to.side_effect = download
        call_command("finalize_uploads", stdout=io.StringIO())
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.state, "verifying")
        job = UploadFinalizationJob.objects.get(upload_session=self.upload)
        self.assertEqual((job.state, job.attempts), ("processing", 2))
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "reserved")
        self.adapter.quarantine_object.assert_not_called()

    def test_error_after_commit_converges_to_done_and_keeps_consumed_quota(self):
        def finish_then_error(*args, **kwargs):
            finalize_verified_upload(self.upload, self.payload, self.editor)
            raise StorageIntegrityError("Late error after a successful publication")

        self.adapter.download_to.side_effect = finish_then_error
        call_command("finalize_uploads", stdout=io.StringIO())
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.state, "available")
        self.assertEqual(UploadFinalizationJob.objects.get(upload_session=self.upload).state, "done")
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "consumed")
        self.adapter.quarantine_object.assert_not_called()

    def test_retryable_error_retains_reservation_and_next_attempt_succeeds(self):
        self.adapter.complete_multipart.side_effect = StorageRetryableError("Temporary provider outage")
        with self.assertLogs("files.management.commands.finalize_uploads", level="ERROR"):
            call_command("finalize_uploads", stdout=io.StringIO())
        job = UploadFinalizationJob.objects.get(upload_session=self.upload)
        self.assertEqual((job.state, job.attempts), ("pending", 1))
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "reserved")
        self.adapter.complete_multipart.side_effect = None
        call_command("finalize_uploads", stdout=io.StringIO())
        job.refresh_from_db()
        self.assertEqual((job.state, job.attempts), ("done", 2))
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "consumed")

    @override_settings(SECUREDRIVE_UPLOAD_SCANNER="fixture.scanner")
    def test_scanner_rejection_preserves_failure_reason_and_releases_quota(self):
        with patch("files.finalization.import_string", return_value=lambda *args: False):
            with self.assertLogs("files.management.commands.finalize_uploads", level="ERROR"):
                call_command("finalize_uploads", stdout=io.StringIO())
        self.upload.refresh_from_db()
        self.assertEqual((self.upload.state, self.upload.failure_code), ("failed", "security_scan_rejected"))
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "released")
        self.adapter.publish_verified_object.assert_not_called()

    @override_settings(SECUREDRIVE_UPLOAD_SCANNER="fixture.scanner")
    def test_superseded_scanner_cannot_fail_new_attempt(self):
        def scan(*args):
            self.reclaim()
            return False

        with patch("files.finalization.import_string", return_value=scan):
            call_command("finalize_uploads", stdout=io.StringIO())
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.state, "scanning")
        self.assertEqual(UploadFinalizationJob.objects.get(upload_session=self.upload).state, "processing")
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "reserved")
        self.adapter.quarantine_object.assert_not_called()
