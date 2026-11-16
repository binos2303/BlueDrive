"""Regression tests for memory-bounded finalization and durable publication."""
import hashlib
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from files.finalization import finalize_verified_upload
from files.models import File, FileVersion, StorageLocation, UploadSession
from files.storage_adapters.base import ObjectStat, StorageRetryableError


@override_settings(SECUREDRIVE_UPLOAD_SCANNER="")
class FinalizationStreamTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="finalization-stream-owner", password="test-secret-123!"
        )
        self.data = b"safe streaming data\n"
        self.sha = hashlib.sha256(self.data).hexdigest()
        self.session = UploadSession.objects.create(
            tenant=self.user.personal_tenant,
            initiated_by=self.user,
            client_name="sample.txt",
            expected_size_bytes=len(self.data),
            expected_sha256=self.sha,
            object_key="staging/" + "a" * 32,
            state=UploadSession.State.VERIFYING,
            expires_at=timezone.now() + timedelta(hours=1),
        )

    @patch("files.finalization.finalize_upload_quota")
    @patch("files.finalization.get_storage_adapter")
    def test_stream_publication_uses_s3_copy_and_records_integrity(self, get_adapter, quota):
        storage = get_adapter.return_value
        storage.publish_verified_object.return_value = ObjectStat(size_bytes=len(self.data), version_id="published-v1")
        storage.create_object_key.return_value = "primary/" + "b" * 32
        with tempfile.SpooledTemporaryFile(max_size=4, mode="w+b") as stream:
            stream.write(self.data)
            self.assertTrue(stream._rolled)
            result = finalize_verified_upload(
                self.session, stream, self.user,
                verified_sha256=self.sha, verified_etag="etag-2",
            )
        self.assertEqual(result["state"], UploadSession.State.AVAILABLE)
        args = storage.publish_verified_object.call_args
        self.assertEqual(args.args[:2], (
            "staging/" + "a" * 32, "primary/" + "b" * 32
        ))
        self.assertEqual(args.kwargs["expected_source_etag"], "etag-2")
        self.assertEqual(args.kwargs["expected_sha256"], self.sha)
        storage.put_object.assert_not_called()
        storage.delete_object.assert_called_once_with("staging/" + "a" * 32)
        file = File.objects.get(pk=result["file_id"])
        self.assertEqual(file.hash_sha256, self.sha)
        self.assertEqual(FileVersion.objects.get(file=file).sha256, self.sha)
        self.assertEqual(StorageLocation.objects.get(file_version__file=file).checksum, self.sha)
        self.assertEqual(StorageLocation.objects.get(file_version__file=file).provider_version_id, "published-v1")
        self.assertEqual(StorageLocation.objects.get(file_version__file=file).storage_config.provider, "s3")
        quota.assert_called_once()

    @patch("files.finalization.finalize_upload_quota")
    @patch("files.finalization.get_storage_adapter")
    def test_copy_failure_preserves_pending_session_and_destination(self, get_adapter, quota):
        storage = get_adapter.return_value
        storage.create_object_key.return_value = "primary/" + "b" * 32
        storage.publish_verified_object.side_effect = StorageRetryableError("S3 unavailable")
        with tempfile.SpooledTemporaryFile(max_size=4, mode="w+b") as stream:
            stream.write(self.data)
            with self.assertRaises(StorageRetryableError):
                finalize_verified_upload(
                    self.session, stream, self.user,
                    verified_sha256=self.sha,
                )
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, UploadSession.State.VERIFYING)
        self.assertEqual(self.session.final_object_key, "primary/" + "b" * 32)
        self.assertFalse(File.objects.filter(tenant=self.session.tenant, file_name="sample.txt").exists())
        storage.delete_object.assert_not_called()
        quota.assert_not_called()

    @patch("files.finalization.finalize_upload_quota")
    @patch("files.finalization.get_storage_adapter")
    def test_stream_hash_mismatch_fails_before_copy(self, get_adapter, quota):
        with tempfile.SpooledTemporaryFile(max_size=4, mode="w+b") as stream:
            stream.write(self.data)
            with self.assertRaises(ValueError):
                finalize_verified_upload(
                    self.session, stream, self.user,
                    verified_sha256="0" * 64,
                )
        get_adapter.assert_not_called()
        quota.assert_not_called()

    @patch("files.finalization.finalize_upload_quota")
    @patch("files.finalization.get_storage_adapter")
    def test_legacy_bytes_do_not_require_staging_copy(self, get_adapter, quota):
        storage = get_adapter.return_value
        storage.put_object.return_value = ObjectStat(size_bytes=len(self.data))
        storage.create_object_key.return_value = "primary/" + "b" * 32
        finalize_verified_upload(self.session, self.data, self.user)
        storage.put_object.assert_called_once()
        storage.publish_verified_object.assert_not_called()
