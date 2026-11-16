import base64
import hashlib
import unittest
from django.test import override_settings
from io import BytesIO, StringIO
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, unquote, urlsplit

from botocore.exceptions import BotoCoreError, ClientError, ReadTimeoutError

from files.storage_adapters.base import (
    MultipartPart,
    ObjectStat,
    StorageIntegrityError,
    StorageNotFoundError,
    StorageConfigurationError,
    StorageNonRetryableError,
    StorageRetryableError,
)
from files.storage_adapters.s3_compatible import S3CompatibleStorageAdapter


class StorageAdapterTests(unittest.TestCase):
    def build_adapter(self, client, **kwargs):
        if isinstance(client, Mock):
            if isinstance(client.copy_object.return_value, Mock):
                client.copy_object.return_value = {}
            if isinstance(client.put_object.return_value, Mock):
                client.put_object.return_value = {}
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

    def test_list_uploaded_parts_paginates_without_completing(self):
        client = Mock()
        client.list_parts.side_effect = [
            {"Parts": [{"PartNumber": 1, "ETag": '"etag-1"', "Size": 8}],
             "IsTruncated": True, "NextPartNumberMarker": 1},
            {"Parts": [{"PartNumber": 2, "ETag": '"etag-2"', "Size": 3}],
             "IsTruncated": False},
        ]
        result = self.build_adapter(client).list_uploaded_parts(
            "staging/" + "a" * 32, "multipart-id"
        )
        self.assertEqual([(p.part_number, p.etag, p.size_bytes) for p in result], [
            (1, '"etag-1"', 8), (2, '"etag-2"', 3),
        ])
        self.assertEqual(client.list_parts.call_count, 2)
        self.assertEqual(client.list_parts.call_args.kwargs["PartNumberMarker"], 1)
        client.complete_multipart_upload.assert_not_called()

    def test_list_parts_rejects_nonadvancing_page_marker(self):
        client = Mock()
        client.list_parts.return_value = {
            "Parts": [{"PartNumber": 1, "ETag": '"etag-1"', "Size": 8}],
            "IsTruncated": True,
            "NextPartNumberMarker": 0,
        }
        with self.assertRaises(StorageIntegrityError):
            self.build_adapter(client).list_uploaded_parts(
                "staging/" + "a" * 32, "multipart-id"
            )
        self.assertEqual(client.list_parts.call_count, 1)

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

    def test_download_url_forces_safe_attachment_and_rejects_invalid_keys_and_expiry(self):
        client = Mock()
        adapter = self.build_adapter(client)
        adapter.create_download_url("primary/" + "a" * 32, expires_in=180, download_name="Báo cáo\r\n../tháng.txt")
        params = client.generate_presigned_url.call_args.kwargs["Params"]
        self.assertEqual(params["ResponseContentType"], "application/octet-stream")
        self.assertEqual(params["ResponseCacheControl"], "private, no-store")
        self.assertTrue(params["ResponseContentDisposition"].startswith("attachment; filename*=UTF-8''"))
        self.assertIn("Báo cáo", unquote(params["ResponseContentDisposition"]))
        self.assertNotIn("\r", unquote(params["ResponseContentDisposition"]))
        self.assertNotIn("\n", unquote(params["ResponseContentDisposition"]))
        for key, expiry in [("../../secret", 180), ("primary/" + "a" * 32, 0), ("primary/" + "a" * 32, 301)]:
            with self.subTest(key=key, expiry=expiry), self.assertRaises(StorageNonRetryableError):
                adapter.create_download_url(key, expires_in=expiry)

    def test_public_endpoint_uses_its_own_signer_without_changing_storage_client(self):
        internal, public = Mock(), Mock()
        with patch("files.storage_adapters.s3_compatible.boto3.client", return_value=public) as build:
            adapter = self.build_adapter(internal, public_endpoint_url="https://download.example.invalid/s3", access_key_id="test-key", secret_access_key="test-secret")
            build.assert_not_called()
            adapter.create_download_url("primary/" + "a" * 32, expires_in=180)
            self.assertEqual(build.call_args.kwargs["endpoint_url"], "https://download.example.invalid/s3")
            self.assertEqual(build.call_args.kwargs["config"].signature_version, "s3v4")
        public.generate_presigned_url.assert_called_once()
        internal.generate_presigned_url.assert_not_called()
        internal.head_object.return_value = {"ContentLength": 12}
        self.assertEqual(adapter.stat_object("primary/" + "a" * 32).size_bytes, 12)

    def test_same_public_endpoint_reuses_client_and_invalid_endpoint_is_rejected(self):
        with patch("files.storage_adapters.s3_compatible.boto3.client") as build:
            self.build_adapter(Mock(), public_endpoint_url="http://localhost:9000/")
            build.assert_not_called()
        for endpoint in ("file:///tmp/a", "https://user:secret@store.invalid", "https://store.invalid?a=b", "https://store.invalid/#fragment"):
            with self.subTest(endpoint=endpoint), self.assertRaises(StorageConfigurationError):
                self.build_adapter(Mock(), public_endpoint_url=endpoint)

    def test_upload_uses_public_signer_and_preserves_internal_operations(self):
        internal, public = Mock(), Mock()
        with patch("files.storage_adapters.s3_compatible.boto3.client", return_value=public):
            adapter = self.build_adapter(internal, public_endpoint_url="http://s3.localhost:8333", public_upload_endpoint=True)
            adapter.create_part_upload_url("staging/" + "a" * 32, "upload-id", 1, expires_in=60)
        public.generate_presigned_url.assert_called_once()
        internal.generate_presigned_url.assert_not_called()
        internal.head_object.return_value = {"ContentLength": 1}
        self.assertEqual(adapter.stat_object("staging/" + "a" * 32).size_bytes, 1)

    @override_settings(SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL="http://s3.localhost:8333", SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED=False)
    def test_global_factory_uses_public_upload_endpoint_with_direct_download_off(self):
        from files.storage_adapters.factory import get_storage_adapter
        with override_settings(SECUREDRIVE_STORAGE_ENDPOINT_URL="http://internal.invalid:8333"), patch(
            "files.storage_adapters.factory.S3CompatibleStorageAdapter"
        ) as build:
            get_storage_adapter()
        self.assertEqual(build.call_args.kwargs["public_endpoint_url"], "http://s3.localhost:8333")
        self.assertTrue(build.call_args.kwargs["public_upload_endpoint"])

    def test_real_sigv4_signer_binds_public_host_path_unicode_headers_and_expiry(self):
        adapter = S3CompatibleStorageAdapter(
            endpoint_url="http://internal.invalid:9000", public_endpoint_url="https://download.example.invalid/s3",
            bucket="test-bucket", access_key_id="test-key", secret_access_key="test-secret", region="us-east-1",
        )
        signed = adapter.create_download_url("primary/" + "a" * 32, expires_in=180, download_name="Tài liệu.txt")
        parsed = urlsplit(signed.url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "download.example.invalid")
        self.assertEqual(parsed.path, "/s3/test-bucket/primary/" + "a" * 32)
        self.assertEqual(query["X-Amz-Algorithm"], ["AWS4-HMAC-SHA256"])
        self.assertEqual(query["X-Amz-Expires"], ["180"])
        self.assertEqual(query["response-content-type"], ["application/octet-stream"])
        self.assertIn("Tài liệu.txt", unquote(query["response-content-disposition"][0]))
        self.assertNotIn("X-Amz", repr(signed))

    def test_download_signing_error_does_not_expose_sdk_details(self):
        client = Mock()
        client.generate_presigned_url.side_effect = BotoCoreError()
        with self.assertRaisesRegex(StorageNonRetryableError, "Could not create a download authorization"):
            self.build_adapter(client).create_download_url("primary/" + "a" * 32, expires_in=180)

    def test_version_id_is_used_for_head_get_and_presigned_get(self):
        client = Mock()
        client.head_object.return_value = {"ContentLength": 4, "VersionId": "published-v1"}
        client.get_object.return_value = {"Body": BytesIO(b"data"), "VersionId": "published-v1"}
        adapter = self.build_adapter(client)
        key = "primary/" + "a" * 32
        self.assertEqual(adapter.stat_object(key, version_id="published-v1").version_id, "published-v1")
        self.assertEqual(client.head_object.call_args.kwargs["VersionId"], "published-v1")
        adapter.open_object(key, version_id="published-v1")
        self.assertEqual(client.get_object.call_args.kwargs["VersionId"], "published-v1")
        adapter.create_download_url(key, expires_in=180, version_id="published-v1")
        self.assertEqual(client.generate_presigned_url.call_args.kwargs["Params"]["VersionId"], "published-v1")
        with self.assertRaises(StorageNonRetryableError):
            adapter.open_object(key, version_id="bad\r\nversion")

    def test_copy_publication_verifies_and_returns_the_written_version_not_latest(self):
        client = Mock()
        client.copy_object.return_value = {"VersionId": "copied-v1"}
        client.head_object.side_effect = [
            {"ContentLength": 3, "ETag": '"source"', "Metadata": {"securedrive-upload-id": "session"}},
            {"ContentLength": 3, "VersionId": "copied-v1", "Metadata": {"securedrive-upload-id": "session", "securedrive-sha256": "a" * 64}},
        ]
        result = self.build_adapter(client).publish_verified_object(
            "staging/" + "a" * 32, "primary/" + "b" * 32,
            expected_size=3, expected_sha256="a" * 64, upload_session_id="session",
        )
        self.assertEqual(result.version_id, "copied-v1")
        self.assertEqual(client.head_object.call_args.kwargs["VersionId"], "copied-v1")

    def test_versioned_delete_paginates_and_deletes_only_exact_key_including_markers(self):
        client = Mock()
        key = "primary/" + "a" * 32
        client.list_object_versions.side_effect = [
            {"Versions": [{"Key": key, "VersionId": "v2"}], "IsTruncated": True,
             "NextKeyMarker": key, "NextVersionIdMarker": "v2"},
            {"Versions": [{"Key": key, "VersionId": "v1"}, {"Key": key + "/sibling", "VersionId": "sibling"}],
             "DeleteMarkers": [{"Key": key, "VersionId": "marker"}]},
        ]
        client.delete_objects.return_value = {}
        self.build_adapter(client).delete_object(key)
        self.assertEqual(client.list_object_versions.call_args.kwargs["VersionIdMarker"], "v2")
        self.assertEqual(client.delete_objects.call_args.kwargs["Delete"]["Objects"], [
            {"Key": key, "VersionId": "v2"}, {"Key": key, "VersionId": "v1"}, {"Key": key, "VersionId": "marker"},
        ])
        client.delete_object.assert_not_called()

    def test_versioned_delete_rejects_partial_failure_and_repeating_pagination(self):
        key = "primary/" + "a" * 32
        client = Mock()
        client.list_object_versions.return_value = {"Versions": [{"Key": key, "VersionId": "v1"}]}
        client.delete_objects.return_value = {"Errors": [{"Code": "AccessDenied"}]}
        with self.assertRaises(StorageNonRetryableError):
            self.build_adapter(client).delete_object(key)
        client.list_object_versions.return_value = {"IsTruncated": True, "NextKeyMarker": key, "NextVersionIdMarker": "v1"}
        with self.assertRaises(StorageIntegrityError):
            self.build_adapter(client).delete_object(key)

    def test_delete_already_absent_key_does_not_create_a_delete_marker(self):
        client = Mock()
        client.list_object_versions.return_value = {}
        self.build_adapter(client).delete_object("primary/" + "a" * 32)
        client.delete_objects.assert_not_called()
        client.delete_object.assert_not_called()

    def test_missing_pinned_version_is_a_typed_not_found(self):
        client = Mock()
        client.head_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchVersion"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadObject",
        )
        with self.assertRaises(StorageNotFoundError):
            self.build_adapter(client).stat_object("primary/" + "a" * 32, version_id="removed-version")

    @override_settings(SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED=False, SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL="")
    def test_empty_public_endpoint_keeps_internal_upload_signer(self):
        from files.storage_adapters import get_storage_adapter
        with patch("files.storage_adapters.factory.S3CompatibleStorageAdapter") as build:
            get_storage_adapter()
        self.assertEqual(build.call_args.kwargs["public_endpoint_url"], "")
        self.assertFalse(build.call_args.kwargs["public_upload_endpoint"])

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

    def test_put_preserves_migration_metadata_and_canonical_checksum(self):
        payload = b"preserved source bytes"
        digest = hashlib.sha256(payload).hexdigest()
        metadata = {"Source-Receipt": "source-version-1", "securedrive-upload-id": "upload-1",
                    "securedrive-sha256": digest.upper()}
        client = Mock()
        client.head_object.return_value = {
            "ContentLength": len(payload),
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(digest)).decode(),
            "ChecksumType": "FULL_OBJECT", "VersionId": "target-version-1",
        }
        client.put_object.return_value = {"VersionId": "target-version-1"}
        self.build_adapter(client).put_object(
            "primary/" + "a" * 32, BytesIO(payload), size_bytes=len(payload),
            sha256_hex=digest, metadata=metadata,
        )
        self.assertEqual(client.put_object.call_args.kwargs["Metadata"], {
            "source-receipt": "source-version-1", "securedrive-upload-id": "upload-1",
            "securedrive-sha256": digest,
        })
        self.assertEqual(metadata["securedrive-sha256"], digest.upper())
        self.assertEqual(client.head_object.call_args.kwargs["VersionId"], "target-version-1")

    def test_put_rejects_conflicting_or_ambiguous_metadata_before_writing(self):
        for metadata, error in (
            ({"securedrive-sha256": "b" * 64}, StorageIntegrityError),
            ({"Receipt": "one", "receipt": "two"}, StorageNonRetryableError),
            ({"receipt": None}, StorageNonRetryableError),
            ([("receipt", "value")], StorageNonRetryableError),
        ):
            with self.subTest(metadata=metadata):
                client = Mock()
                with self.assertRaises(error):
                    self.build_adapter(client).put_object(
                        "primary/" + "a" * 32, BytesIO(b"x"), size_bytes=1,
                        sha256_hex="a" * 64, metadata=metadata,
                    )
                client.put_object.assert_not_called()
                client.head_object.assert_not_called()

    def test_download_size_limit_rejects_provider_declared_oversize(self):
        client = Mock()
        client.get_object.return_value = {
            "Body": BytesIO(b"large"), "ContentLength": 50,
        }
        destination = BytesIO()
        with self.assertRaises(StorageIntegrityError):
            self.build_adapter(client).download_to(
                "staging/" + "a" * 32, destination, max_bytes=10
            )
        self.assertEqual(destination.getvalue(), b"")

    def test_download_size_limit_rejects_stream_longer_than_declared(self):
        client = Mock()
        client.get_object.return_value = {
            "Body": BytesIO(b"longer than metadata"), "ContentLength": 5,
        }
        with self.assertRaises(StorageIntegrityError):
            self.build_adapter(client).download_to(
                "staging/" + "a" * 32, BytesIO(), max_bytes=10
            )

    def test_publish_verified_object_uses_conditional_server_side_copy(self):
        content = b"verified multipart bytes"
        digest = hashlib.sha256(content).hexdigest()
        session_id = "session-uuid"
        client = Mock()
        client.head_object.side_effect = [
            {
                "ContentLength": len(content), "ETag": '"source-etag-2"',
                "Metadata": {"securedrive-upload-id": session_id},
            },
            {
                "ContentLength": len(content), "ETag": '"destination-etag"',
                "Metadata": {
                    "securedrive-sha256": digest,
                    "securedrive-upload-id": session_id,
                },
            },
        ]
        storage = self.build_adapter(client)
        stat = storage.publish_verified_object(
            "staging/" + "a" * 32, "primary/" + "b" * 32,
            expected_size=len(content), expected_sha256=digest,
            upload_session_id=session_id, content_type="text/plain",
            expected_source_etag="source-etag-2",
        )
        self.assertEqual(stat.size_bytes, len(content))
        self.assertEqual(client.copy_object.call_count, 1)
        params = client.copy_object.call_args.kwargs
        self.assertEqual(params["CopySourceIfMatch"], '"source-etag-2"')
        self.assertEqual(params["MetadataDirective"], "REPLACE")
        self.assertEqual(params["Metadata"]["securedrive-sha256"], digest)
        self.assertEqual(params["ContentType"], "text/plain")
        client.put_object.assert_not_called()
        client.get_object.assert_not_called()
        client.delete_object.assert_not_called()

    def test_publish_rejects_source_changed_since_full_sha256(self):
        client = Mock()
        client.head_object.return_value = {
            "ContentLength": 3, "ETag": '"new-etag"',
            "Metadata": {"securedrive-upload-id": "session-uuid"},
        }
        with self.assertRaises(StorageIntegrityError):
            self.build_adapter(client).publish_verified_object(
                "staging/" + "a" * 32, "primary/" + "b" * 32,
                expected_size=3, expected_sha256="a" * 64,
                upload_session_id="session-uuid", expected_source_etag="old-etag",
            )
        client.copy_object.assert_not_called()

    def test_publish_rejects_destination_without_verified_metadata(self):
        client = Mock()
        client.head_object.side_effect = [
            {"ContentLength": 3, "ETag": '"etag"',
             "Metadata": {"securedrive-upload-id": "session-uuid"}},
            {"ContentLength": 3, "Metadata": {}},
        ]
        with self.assertRaises(StorageIntegrityError):
            self.build_adapter(client).publish_verified_object(
                "staging/" + "a" * 32, "primary/" + "b" * 32,
                expected_size=3, expected_sha256="a" * 64,
                upload_session_id="session-uuid",
            )

    def test_publish_recovers_lost_copy_response_by_head(self):
        client = Mock()
        client.copy_object.side_effect = ReadTimeoutError(
            endpoint_url="http://storage", error="response lost"
        )
        client.head_object.side_effect = [
            {"ContentLength": 3, "ETag": '"etag"',
             "Metadata": {"securedrive-upload-id": "session-uuid"}},
            {"ContentLength": 3,
             "Metadata": {
                 "securedrive-sha256": "a" * 64,
                 "securedrive-upload-id": "session-uuid",
             }},
        ]
        result = self.build_adapter(client).publish_verified_object(
            "staging/" + "a" * 32, "primary/" + "b" * 32,
            expected_size=3, expected_sha256="a" * 64,
            upload_session_id="session-uuid",
        )
        self.assertEqual(result.size_bytes, 3)
        self.assertEqual(client.copy_object.call_count, 1)


class ConnectionProbeTests(unittest.TestCase):
    def run_probe(self, *, cleanup_error=None):
        from django.core.management.base import CommandError
        from files.management.commands.check_connections import Command

        stdout, stderr = StringIO(), StringIO()
        adapter = Mock()
        adapter.put_object.side_effect = lambda key, body, **kwargs: ObjectStat(size_bytes=kwargs['size_bytes'])
        adapter.open_object.side_effect = lambda key: BytesIO(adapter.put_object.call_args.args[1].getvalue())
        adapter.delete_object.side_effect = cleanup_error
        with patch('files.management.commands.check_connections.connection') as database, patch(
            'files.management.commands.check_connections.get_storage_adapter', return_value=adapter,
        ):
            database.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
            command = Command(stdout=stdout, stderr=stderr, no_color=True)
            if cleanup_error:
                with self.assertRaises(CommandError):
                    command.handle()
            else:
                command.handle()
        return adapter, stdout.getvalue(), stderr.getvalue()

    def test_failed_probe_cleanup_never_reports_all_probes_passed(self):
        adapter, stdout, stderr = self.run_probe(cleanup_error=RuntimeError('private provider detail'))
        adapter.delete_object.assert_called_once_with(adapter.create_object_key.return_value)
        self.assertNotIn('All connection probes passed', stdout)
        self.assertIn('could not be deleted', stderr)
        self.assertNotIn('private provider detail', stdout + stderr)

    def test_successful_probe_checks_and_removes_its_own_object(self):
        adapter, stdout, stderr = self.run_probe()
        self.assertIn('All connection probes passed', stdout)
        adapter.delete_object.assert_called_once_with(adapter.create_object_key.return_value)
        self.assertEqual(stderr, '')
