import json
import os
import unittest
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from django.conf import settings

from files.storage_adapters import get_storage_adapter
from files.storage_adapters.base import (
    MultipartPart,
    StorageNonRetryableError,
    StorageNotFoundError,
    StorageRetryableError,
)
from files.storage_adapters.s3_compatible import S3CompatibleStorageAdapter


MINIO_ENABLED = os.getenv("SECUREDRIVE_MINIO_INTEGRATION", "").lower() in {
    "1",
    "true",
    "yes",
}


@unittest.skipUnless(
    MINIO_ENABLED,
    "Set SECUREDRIVE_MINIO_INTEGRATION=true to run against a disposable MinIO bucket.",
)
class MinIOStorageIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = get_storage_adapter()

    def test_missing_object_is_a_typed_not_found(self):
        key = self.adapter.create_object_key("final")
        with self.assertRaises(StorageNotFoundError):
            self.adapter.stat_object(key)

    def test_repeated_abort_and_delete_are_safe(self):
        key = self.adapter.create_object_key("quarantine")
        upload = self.adapter.initiate_multipart(
            key, upload_session_id="integration-test-session"
        )
        self.adapter.abort_multipart(key, upload.upload_id)
        self.adapter.abort_multipart(key, upload.upload_id)
        self.adapter.delete_object(key)
        self.adapter.delete_object(key)

    def test_repeated_multipart_complete_returns_the_same_verified_object(self):
        payload = b"repeatable-complete"
        key = self.adapter.create_object_key("quarantine")
        upload = self.adapter.initiate_multipart(
            key, upload_session_id="integration-repeat-complete"
        )
        try:
            uploaded = self.adapter._client.upload_part(
                Bucket=settings.SECUREDRIVE_STORAGE_BUCKET,
                Key=key,
                UploadId=upload.upload_id,
                PartNumber=1,
                Body=payload,
            )
            parts = [MultipartPart(part_number=1, etag=uploaded["ETag"])]
            first = self.adapter.complete_multipart(
                key, upload.upload_id, parts, expected_size=len(payload)
            )
            repeated = self.adapter.complete_multipart(
                key, upload.upload_id, parts, expected_size=len(payload)
            )
            self.assertEqual(first.size_bytes, len(payload))
            self.assertEqual(repeated.size_bytes, first.size_bytes)
            self.assertEqual(
                repeated.metadata.get("securedrive-upload-id"), "integration-repeat-complete"
            )
        finally:
            self.adapter.abort_multipart(key, upload.upload_id)
            self.adapter.delete_object(key)

    def test_wrong_credentials_are_non_retryable_and_redacted(self):
        adapter = S3CompatibleStorageAdapter(
            endpoint_url=settings.SECUREDRIVE_STORAGE_ENDPOINT_URL,
            bucket=settings.SECUREDRIVE_STORAGE_BUCKET,
            region=settings.SECUREDRIVE_STORAGE_REGION,
            addressing_style=settings.SECUREDRIVE_STORAGE_ADDRESSING_STYLE,
            access_key_id="invalid-integration-access-key",
            secret_access_key="invalid-integration-secret-key",
            tls_verify=settings.SECUREDRIVE_STORAGE_TLS_VERIFY,
            ca_bundle=settings.SECUREDRIVE_STORAGE_CA_BUNDLE,
            max_attempts=3,
        )
        with self.assertRaises(StorageNonRetryableError) as raised:
            adapter.stat_object(self.adapter.create_object_key("final"))
        self.assertNotIn("invalid-integration", str(raised.exception))

    def test_failed_provider_complete_is_non_retryable(self):
        key = self.adapter.create_object_key("quarantine")
        upload = self.adapter.initiate_multipart(
            key, upload_session_id="integration-failed-complete"
        )
        try:
            # The provider has one valid part; a tampered ETag must fail at multipart completion.
            self.adapter._client.upload_part(
                Bucket=settings.SECUREDRIVE_STORAGE_BUCKET,
                Key=key,
                UploadId=upload.upload_id,
                PartNumber=1,
                Body=b"small-final-part",
            )
            altered_etag = '"deliberately-wrong-etag"'
            with patch.object(
                self.adapter._client,
                "list_parts",
                return_value={
                    "Parts": [
                        {
                            "PartNumber": 1,
                            "ETag": altered_etag,
                            "Size": len(b"small-final-part"),
                        }
                    ],
                    "IsTruncated": False,
                },
            ):
                with self.assertRaises(StorageNonRetryableError):
                    self.adapter.complete_multipart(
                        key,
                        upload.upload_id,
                        [MultipartPart(part_number=1, etag=altered_etag)],
                        expected_size=len(b"small-final-part"),
                    )
        finally:
            self.adapter.abort_multipart(key, upload.upload_id)
            self.adapter.delete_object(key)

    def test_timeout_against_configured_fault_injection_endpoint_is_bounded(self):
        endpoint = os.getenv("SECUREDRIVE_MINIO_TIMEOUT_TEST_ENDPOINT", "").strip()
        if not endpoint:
            self.skipTest(
                "Configure a local delay/fault proxy endpoint for timeout integration coverage."
            )
        control_endpoint = os.getenv(
            "SECUREDRIVE_MINIO_TIMEOUT_CONTROL_ENDPOINT", "http://127.0.0.1:8474"
        ).rstrip("/")
        proxy_name = "securedrive-timeout-test"

        def toxiproxy(method, path, payload=None):
            request = Request(
                f"{control_endpoint}{path}",
                data=json.dumps(payload).encode() if payload is not None else None,
                headers={"Content-Type": "application/json"},
                method=method,
            )
            try:
                with urlopen(request, timeout=2):
                    return
            except HTTPError as error:
                if method == "DELETE" and error.code == 404:
                    return
                raise

        toxiproxy("DELETE", f"/proxies/{proxy_name}")
        toxiproxy(
            "POST",
            "/proxies",
            {
                "name": proxy_name,
                "listen": "0.0.0.0:8666",
                "upstream": os.getenv("SECUREDRIVE_MINIO_TIMEOUT_UPSTREAM", "minio:9000"),
                "enabled": True,
            },
        )
        toxiproxy(
            "POST",
            f"/proxies/{proxy_name}/toxics",
            {
                "name": "downstream-delay",
                "type": "latency",
                "stream": "downstream",
                "toxicity": 1.0,
                "attributes": {"latency": 250, "jitter": 0},
            },
        )
        adapter = S3CompatibleStorageAdapter(
            endpoint_url=endpoint,
            bucket=settings.SECUREDRIVE_STORAGE_BUCKET,
            region=settings.SECUREDRIVE_STORAGE_REGION,
            addressing_style=settings.SECUREDRIVE_STORAGE_ADDRESSING_STYLE,
            access_key_id=settings.SECUREDRIVE_STORAGE_ACCESS_KEY_ID,
            secret_access_key=settings.SECUREDRIVE_STORAGE_SECRET_ACCESS_KEY,
            tls_verify=settings.SECUREDRIVE_STORAGE_TLS_VERIFY,
            ca_bundle=settings.SECUREDRIVE_STORAGE_CA_BUNDLE,
            connect_timeout=0.1,
            read_timeout=0.1,
            max_attempts=2,
        )
        try:
            with self.assertRaises(StorageRetryableError):
                adapter.stat_object(self.adapter.create_object_key("final"))
        finally:
            toxiproxy("DELETE", f"/proxies/{proxy_name}/toxics/downstream-delay")
            toxiproxy("DELETE", f"/proxies/{proxy_name}")

    def test_checksum_and_size_verification(self):
        import hashlib

        content = b"minio adapter integration content"
        checksum = hashlib.sha256(content).hexdigest()
        key = self.adapter.create_object_key("final")
        try:
            stat = self.adapter.put_object(
                key,
                BytesIO(content),
                size_bytes=len(content),
                sha256_hex=checksum,
            )
            self.assertEqual(stat.size_bytes, len(content))
            self.assertEqual(
                self.adapter.verify_object(
                    key, expected_size=len(content), expected_sha256=checksum
                ).size_bytes,
                len(content),
            )
        finally:
            self.adapter.delete_object(key)
