"""Upload API → SeaweedFS thật → worker hiện có → download và quota."""
import hashlib
import io
import os
import unittest
import uuid

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import QuotaAccount
from files.models import File, StorageLocation, UploadFinalizationJob, UploadSession
from files.storage_adapters import get_storage_adapter
from files.tests import test_seaweedfs_integration as s3_gate
from files.views import _decrypt_file


@unittest.skipUnless(os.getenv("SEAWEEDFS_INTEGRATION") == "1", "BLOCKED: cần SeaweedFS thật; không mock worker.")
class SeaweedFSFinalizerIntegrationTests(TestCase):
    def setUp(self):
        s3_gate.SeaweedFSIntegrationTests.setUpClass()
        self.addCleanup(s3_gate.SeaweedFSIntegrationTests.tearDownClass)
        self.enterContext(self.settings(
            DEBUG=True, SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED=False,
            SECUREDRIVE_STORAGE_ENDPOINT_URL=os.environ["SEAWEED_S3_ENDPOINT"],
            SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL=os.environ["SEAWEED_S3_PUBLIC_ENDPOINT"],
            SECUREDRIVE_STORAGE_BUCKET=os.environ["SEAWEED_S3_BUCKET"],
            SECUREDRIVE_STORAGE_ACCESS_KEY_ID=os.environ["SEAWEED_S3_ACCESS_KEY"],
            SECUREDRIVE_STORAGE_SECRET_ACCESS_KEY=os.environ["SEAWEED_S3_SECRET_KEY"],
            SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=False,
            SECUREDRIVE_STORAGE_SSE="", SECUREDRIVE_UPLOAD_SCANNER=""))
        self.user = get_user_model().objects.create_user(username="seaweed-gate-" + uuid.uuid4().hex)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.storage = get_storage_adapter()
        self.addCleanup(self.storage._client.close)

    def upload(self, payload, expected_sha256):
        response = self.client.post("/files/api/uploads/", {"name": "seaweed-gate.txt", "size_bytes": len(payload),
            "sha256": expected_sha256}, format="json", HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex)
        self.assertEqual(response.status_code, 201)
        upload_id = response.data["upload_id"]
        session = UploadSession.objects.get(pk=upload_id)
        self.addCleanup(self.storage.delete_object, session.object_key)
        parts = []
        if payload:
            self.addCleanup(self.storage.abort_multipart, session.object_key, session.provider_upload_id)
            authorization = self.client.post(f"/files/api/uploads/{upload_id}/parts/1/authorization/")
            self.assertEqual(authorization.status_code, 200)
            status, headers, _ = s3_gate.http(authorization.data["url"], method="PUT", body=payload, headers=authorization.data["headers"])
            self.assertEqual(status, 200)
            parts = [{"part_number": 1, "etag": headers["ETag"]}]
            resumed = self.client.get(f"/files/api/uploads/{upload_id}/parts/")
            self.assertEqual(resumed.status_code, 200)
            self.assertEqual(resumed.data["parts"][0]["etag"], parts[0]["etag"])
        completed = self.client.post(f"/files/api/uploads/{upload_id}/complete/", {"parts": parts}, format="json")
        self.assertEqual(completed.status_code, 202)
        call_command("finalize_uploads", stdout=io.StringIO())
        session.refresh_from_db()
        for key in (session.final_object_key, session.object_key):
            if key:
                self.addCleanup(self.storage.delete_object, key)
        return session

    def test_existing_worker_publishes_and_downloads_exact_bytes_and_consumes_quota(self):
        for payload in (b"SeaweedFS finalization gate\n", b""):
            with self.subTest(empty=not payload):
                session = self.upload(payload, hashlib.sha256(payload).hexdigest())
                self.assertEqual(session.state, UploadSession.State.AVAILABLE)
                location = StorageLocation.objects.get(file_version__file_id=session.file_id)
                self.assertEqual(location.storage_config.provider, "s3")
                self.assertEqual(_decrypt_file(session.file), payload)
                self.assertEqual(UploadFinalizationJob.objects.get(upload_session=session).state, "done")
        quota = QuotaAccount.objects.get(tenant=self.user.personal_tenant, scope="tenant")
        self.assertEqual(quota.reserved_bytes, 0)
        self.assertEqual(quota.used_bytes, len(b"SeaweedFS finalization gate\n"))

    def test_full_file_hash_mismatch_does_not_publish_and_releases_quota(self):
        session = self.upload(b"tampered contents\n", "0" * 64)
        self.assertEqual(session.state, UploadSession.State.FAILED)
        self.assertIsNone(session.file_id)
        self.assertFalse(File.objects.filter(owner=self.user).exists())
        quota = QuotaAccount.objects.get(tenant=self.user.personal_tenant, scope="tenant")
        self.assertEqual((quota.used_bytes, quota.reserved_bytes), (0, 0))
