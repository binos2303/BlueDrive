from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import QuotaAccount
from files.models import QuotaReservation, UploadSession


class UploadApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="multipart-user", password="test-pass")
        self.tenant = self.user.personal_tenant
        self.account = QuotaAccount.objects.get(tenant=self.tenant, scope=QuotaAccount.Scope.TENANT)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @patch("files.upload_api.get_storage_adapter")
    @patch("files.upload_api.reserve_upload_quota")
    def test_create_reserves_server_owned_session_and_starts_multipart(self, reserve, adapter_factory):
        adapter = adapter_factory.return_value
        adapter.create_object_key.return_value = "quarantine/" + "a" * 32
        adapter.initiate_multipart.return_value.upload_id = "provider-upload-id"
        response = self.client.post("/files/api/uploads/", {
            "name": "document.txt", "size_bytes": 9, "sha256": "a" * 64,
        }, format="json", HTTP_IDEMPOTENCY_KEY="req-1")
        self.assertEqual(response.status_code, 201)
        upload = UploadSession.objects.get(pk=response.data["upload_id"])
        self.assertEqual(upload.tenant_id, self.tenant.pk)
        self.assertEqual(upload.initiated_by_id, self.user.pk)
        self.assertEqual(upload.state, UploadSession.State.UPLOADING)
        self.assertEqual(upload.object_key, "quarantine/" + "a" * 32)
        reserve.assert_called_once_with(upload.pk, self.user)

    def test_malicious_extension_is_rejected_before_session_creation(self):
        response = self.client.post("/files/api/uploads/", {
            "name": "payload.exe", "size_bytes": 12,
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(UploadSession.objects.exists())

    def test_anonymous_cannot_create_upload(self):
        self.client.force_authenticate(user=None)
        response = self.client.post("/files/api/uploads/", {
            "name": "document.txt", "size_bytes": 1,
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_quota_exhaustion_rejects_session_without_finalizing_missing_reservation(self):
        self.account.limit_bytes = 0
        self.account.save(update_fields=["limit_bytes", "updated_at"])
        with (
            patch("files.upload_api.get_storage_adapter") as adapter_factory,
            patch("files.upload_api.finalize_upload_quota") as finalize_quota,
        ):
            adapter_factory.return_value.create_object_key.return_value = "quarantine/" + "b" * 32
            response = self.client.post("/files/api/uploads/", {
                "name": "document.txt", "size_bytes": 9, "sha256": "a" * 64,
            }, format="json")

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.data["failure_code"], "quota_exceeded")
        adapter_factory.return_value.initiate_multipart.assert_not_called()
        finalize_quota.assert_not_called()
        upload = UploadSession.objects.get()
        self.assertEqual(upload.state, UploadSession.State.FAILED)
        self.assertEqual(upload.failure_code, "quota_exceeded")
        self.assertFalse(QuotaReservation.objects.filter(upload_session=upload).exists())

    def test_setup_failure_before_reservation_does_not_finalize_missing_reservation(self):
        with (
            patch("files.upload_api.get_storage_adapter") as adapter_factory,
            patch(
                "files.upload_api.reserve_upload_quota",
                side_effect=RuntimeError("Quota service unavailable"),
            ),
            patch("files.upload_api.finalize_upload_quota") as finalize_quota,
        ):
            adapter_factory.return_value.create_object_key.return_value = "quarantine/" + "e" * 32
            with self.assertLogs("files.upload_api", level="ERROR") as log_output:
                response = self.client.post("/files/api/uploads/", {
                    "name": "document.txt", "size_bytes": 9, "sha256": "a" * 64,
                }, format="json")

        self.assertEqual(response.status_code, 503)
        self.assertTrue(any("Upload initialization failed" in line for line in log_output.output))
        self.assertFalse(any("Unable to release quota after setup failure" in line for line in log_output.output))
        finalize_quota.assert_not_called()
        upload = UploadSession.objects.get()
        self.assertEqual(upload.state, UploadSession.State.FAILED)
        self.assertEqual(upload.failure_code, "storage_setup_failed")
        self.assertFalse(QuotaReservation.objects.filter(upload_session=upload).exists())

    @patch("files.upload_api.get_storage_adapter")
    def test_batch_authorization_returns_one_url_for_each_part(self, adapter_factory):
        adapter = adapter_factory.return_value
        adapter.create_part_upload_url.side_effect = lambda key, provider_id, number, *, expires_in: type(
            "Signed", (), {
                "url": f"https://minio.invalid/part/{number}",
                "method": "PUT",
                "required_headers": {},
            }
        )()
        upload = UploadSession.objects.create(
            tenant=self.tenant,
            initiated_by=self.user,
            client_name="multi-part.bin",
            expected_size_bytes=17 * 1024 * 1024,
            expected_sha256="a" * 64,
            object_key="quarantine/" + "a" * 32,
            provider_upload_id="provider-upload-id",
            expires_at="2035-01-01T00:00:00Z",
            state=UploadSession.State.UPLOADING,
        )
        response = self.client.post(
            f"/files/api/uploads/{upload.pk}/parts/authorizations/",
            {"part_numbers": [2, 1, 3]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([part["part_number"] for part in response.data["parts"]], [1, 2, 3])
        self.assertEqual(adapter.create_part_upload_url.call_count, 3)
        self.assertTrue(all(part["expires_in"] == 180 for part in response.data["parts"]))

    def test_batch_authorization_rejects_duplicate_part_numbers(self):
        upload = UploadSession.objects.create(
            tenant=self.tenant,
            initiated_by=self.user,
            client_name="multi-part.bin",
            expected_size_bytes=9 * 1024 * 1024,
            expected_sha256="a" * 64,
            object_key="quarantine/" + "b" * 32,
            provider_upload_id="provider-upload-id",
            expires_at="2035-01-01T00:00:00Z",
            state=UploadSession.State.UPLOADING,
        )
        response = self.client.post(
            f"/files/api/uploads/{upload.pk}/parts/authorizations/",
            {"part_numbers": [1, 1]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_repeated_complete_for_verifying_session_is_idempotent(self):
        upload = UploadSession.objects.create(
            tenant=self.tenant, initiated_by=self.user, client_name="document.txt",
            expected_size_bytes=1, expected_sha256="a" * 64,
            expires_at="2035-01-01T00:00:00Z", state=UploadSession.State.VERIFYING,
        )
        first = self.client.post(f"/files/api/uploads/{upload.pk}/complete/", {"parts": []}, format="json")
        second = self.client.post(f"/files/api/uploads/{upload.pk}/complete/", {"parts": []}, format="json")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(UploadSession.objects.get(pk=upload.pk).state, UploadSession.State.VERIFYING)

    @patch("files.upload_api.reserve_upload_quota")
    @patch("files.upload_api.get_storage_adapter")
    def test_empty_file_uses_verified_zero_byte_put(self, adapter_factory, reserve):
        adapter = adapter_factory.return_value
        adapter.create_object_key.return_value = "quarantine/" + "c" * 32
        response = self.client.post("/files/api/uploads/", {
            "name": "empty.txt", "size_bytes": 0,
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        adapter.put_object.assert_called_once()
        adapter.initiate_multipart.assert_not_called()

    @patch("files.upload_api.reserve_upload_quota")
    @patch("files.upload_api.get_storage_adapter")
    def test_maximum_size_session_is_accepted_and_part_url_is_short_lived(self, adapter_factory, reserve):
        adapter = adapter_factory.return_value
        adapter.create_object_key.return_value = "quarantine/" + "d" * 32
        adapter.initiate_multipart.return_value.upload_id = "provider-id"
        created = self.client.post("/files/api/uploads/", {
            "name": "large.txt", "size_bytes": 100 * 1024 * 1024, "sha256": "a" * 64,
        }, format="json")
        self.assertEqual(created.status_code, 201)
        upload_id = created.data["upload_id"]
        adapter.create_part_upload_url.return_value.url = "https://minio.invalid/signed"
        adapter.create_part_upload_url.return_value.method = "PUT"
        adapter.create_part_upload_url.return_value.required_headers = {}
        authorized = self.client.post(f"/files/api/uploads/{upload_id}/parts/1/authorization/", {}, format="json")
        self.assertEqual(authorized.status_code, 200)
        adapter.create_part_upload_url.assert_called_once()
        self.assertEqual(adapter.create_part_upload_url.call_args.kwargs["expires_in"], 180)
