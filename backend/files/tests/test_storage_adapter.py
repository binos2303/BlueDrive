import base64
import hashlib
import unittest
from io import BytesIO
from unittest.mock import Mock

from botocore.exceptions import ReadTimeoutError

from files.storage_adapters.base import (
    MultipartPart,
    StorageIntegrityError,
    StorageNonRetryableError,
    StorageRetryableError,
)
from files.storage_adapters.s3_compatible import S3CompatibleStorageAdapter


class StorageAdapterTests(unittest.TestCase):
    def build_adapter(self, client, **kwargs):
        return S3CompatibleStorageAdapter(
            endpoint_url="http://localhost:9000",
            bucket="securedrive-test",
            client=client,
            sleep=Mock(),
            random_uniform=lambda low, high: high,
            **kwargs,
        )

    def test_server_object_keys_never_use_user_filename(self):
        adapter = self.build_adapter(Mock())
        key = adapter.create_object_key("quarantine")
        self.assertRegex(key, r"^quarantine/[0-9a-f]{32}$")
        with self.assertRaises(StorageNonRetryableError):
            adapter.create_object_key("../../customer-name.txt")

    def test_object_checksum_and_size_are_verified(self):
        payload = b"verified bytes"
        digest = hashlib.sha256(payload).hexdigest()
        client = Mock()
        client.head_object.return_value = {
            "ContentLength": len(payload),
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(digest)).decode(),
            "ChecksumType": "FULL_OBJECT",
        }
        stat = self.build_adapter(client).verify_object(
            "final/" + "a" * 32, expected_size=len(payload), expected_sha256=digest
        )
        self.assertEqual(stat.size_bytes, len(payload))
        with self.assertRaises(StorageIntegrityError):
            self.build_adapter(client).verify_object("final/" + "a" * 32, expected_size=999)

    def test_missing_native_checksum_does_not_fall_back_to_etag(self):
        client = Mock()
        client.head_object.return_value = {"ContentLength": 3, "ETag": '"abc"'}
        with self.assertRaises(StorageIntegrityError):
            self.build_adapter(client).verify_object(
                "final/" + "a" * 32, expected_size=3, expected_sha256="a" * 64
            )

    def test_transient_timeout_retries_are_bounded(self):
        client = Mock()
        client.head_object.side_effect = [
            ReadTimeoutError(endpoint_url="http://storage", error="timeout"),
            {"ContentLength": 1},
        ]
        sleep = Mock()
        adapter = S3CompatibleStorageAdapter(
            endpoint_url="http://localhost:9000",
            bucket="securedrive-test",
            client=client,
            max_attempts=2,
            sleep=sleep,
            random_uniform=lambda low, high: high,
        )
        self.assertEqual(adapter.stat_object("final/" + "a" * 32).size_bytes, 1)
        self.assertEqual(client.head_object.call_count, 2)
        self.assertEqual(sleep.call_count, 1)

    def test_transient_timeout_stops_at_retry_limit(self):
        client = Mock()
        client.head_object.side_effect = ReadTimeoutError(
            endpoint_url="http://storage", error="timeout"
        )
        with self.assertRaises(StorageRetryableError):
            self.build_adapter(client, max_attempts=2).stat_object("final/" + "a" * 32)
        self.assertEqual(client.head_object.call_count, 2)

    def test_stream_download_restarts_from_zero_after_read_timeout(self):
        payload = b"complete response"

        class PartialThenTimeout:
            def __init__(self):
                self.read_count = 0

            def read(self, _size):
                self.read_count += 1
                if self.read_count == 1:
                    return b"partial"
                raise ReadTimeoutError(endpoint_url="http://storage", error="timeout")

            def close(self):
                pass

        client = Mock()
        client.get_object.side_effect = [
            {"Body": PartialThenTimeout(), "ContentLength": len(payload)},
            {"Body": BytesIO(payload), "ContentLength": len(payload)},
        ]
        destination = BytesIO(b"old data")
        adapter = self.build_adapter(client, max_attempts=2)
        stat = adapter.download_to("final/" + "a" * 32, destination)
        self.assertEqual(destination.getvalue(), payload)
        self.assertEqual(stat.size_bytes, len(payload))
        self.assertEqual(client.get_object.call_count, 2)

    def test_complete_uses_provider_manifest_and_rejects_mismatch(self):
        client = Mock()
        client.list_parts.return_value = {
            "Parts": [{"PartNumber": 1, "ETag": '"provider-etag"', "Size": 10}],
            "IsTruncated": False,
        }
        adapter = self.build_adapter(client)
        with self.assertRaises(StorageIntegrityError):
            adapter.complete_multipart(
                "quarantine/" + "b" * 32,
                "upload-id",
                [MultipartPart(part_number=1, etag='"client-etag"')],
                expected_size=10,
            )
        client.complete_multipart_upload.assert_not_called()

    def test_completed_object_validates_secure_drive_session_id_not_s3_upload_id(self):
        client = Mock()
        client.list_parts.return_value = {
            "Parts": [{"PartNumber": 1, "ETag": '"provider-etag"', "Size": 10}],
            "IsTruncated": False,
        }
        client.head_object.return_value = {
            "ContentLength": 10,
            "Metadata": {"securedrive-upload-id": "secure-drive-session-uuid"},
        }
        adapter = self.build_adapter(client)
        stat = adapter.complete_multipart(
            "quarantine/" + "b" * 32,
            "s3-provider-multipart-id",
            [MultipartPart(part_number=1, etag='"provider-etag"')],
            expected_size=10,
            expected_upload_session_id="secure-drive-session-uuid",
        )
        self.assertEqual(stat.size_bytes, 10)
        client.complete_multipart_upload.assert_called_once()

    def test_completed_object_rejects_mismatched_secure_drive_session_id(self):
        client = Mock()
        client.list_parts.return_value = {
            "Parts": [{"PartNumber": 1, "ETag": '"provider-etag"', "Size": 10}],
            "IsTruncated": False,
        }
        client.head_object.return_value = {
            "ContentLength": 10,
            "Metadata": {"securedrive-upload-id": "different-session"},
        }
        adapter = self.build_adapter(client)
        with self.assertRaises(StorageIntegrityError):
            adapter.complete_multipart(
                "quarantine/" + "b" * 32,
                "s3-provider-multipart-id",
                [MultipartPart(part_number=1, etag='"provider-etag"')],
                expected_size=10,
                expected_upload_session_id="secure-drive-session-uuid",
            )

    def test_presigned_url_lifetime_is_capped(self):
        adapter = self.build_adapter(Mock(), max_presigned_url_seconds=60)
        with self.assertRaises(StorageNonRetryableError):
            adapter.create_part_upload_url(
                "quarantine/" + "b" * 32, "upload-id", 1, expires_in=61
            )

    def test_put_object_passes_checksum_to_storage_and_verifies_head(self):
        payload = b"ciphertext bytes"
        digest = hashlib.sha256(payload).hexdigest()
        client = Mock()
        client.put_object.return_value = {}
        client.head_object.return_value = {
            "ContentLength": len(payload),
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(digest)).decode(),
            "ChecksumType": "FULL_OBJECT",
        }
        stat = self.build_adapter(client).put_object(
            "final/" + "a" * 32,
            BytesIO(payload),
            size_bytes=len(payload),
            sha256_hex=digest,
        )
        self.assertEqual(stat.size_bytes, len(payload))
        self.assertEqual(
            client.put_object.call_args.kwargs["ChecksumSHA256"],
            base64.b64encode(bytes.fromhex(digest)).decode(),
        )
