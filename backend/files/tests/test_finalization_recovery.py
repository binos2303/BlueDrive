"""Recovery must converge with publication and fence reclaimed worker results."""
import io
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from files.finalization import finalize_verified_upload
from files.models import File, QuotaReservation, UploadFinalizationJob, UploadSession
from files.storage_adapters.base import StorageIntegrityError, StorageNotFoundError, StorageRetryableError
from files.tests.test_finalization_permissions import FinalizationFixture


@override_settings(SECUREDRIVE_UPLOAD_SCANNER="")
class FinalizationRecoveryTests(FinalizationFixture, TestCase):
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
