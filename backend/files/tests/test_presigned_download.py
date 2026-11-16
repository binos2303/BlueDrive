from unittest.mock import Mock, patch
from io import BytesIO
import hashlib

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Workspace, WorkspaceMembership
from files.models import File, FileVersion, StorageConfig, StorageLocation
from files.storage_adapters.base import ObjectStat, PresignedRequest, StorageNotFoundError
from files.tests.test_download_security import DownloadFixture, User
from logs.models import ActivityLog
from sharing.models import Share


@override_settings(
    SECUREDRIVE_STORAGE_ENDPOINT_URL="http://storage-internal:9000",
    SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL="https://storage.example.invalid",
    SECUREDRIVE_DOWNLOAD_URL_SECONDS=180,
    SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED=True,
)
class PresignedDownloadTests(DownloadFixture):
    def setUp(self):
        super().setUp()
        self.storage_location.object_ref = "primary/" + "a" * 32
        self.storage_location.verified_at = timezone.now()
        self.storage_location.checksum = "a" * 64
        self.storage_location.provider_version_id = "verified-version-1"
        self.storage_location.save(update_fields=["object_ref", "verified_at", "checksum", "provider_version_id"])
        self.version.sha256 = "a" * 64
        self.version.verified_at = timezone.now()
        self.version.save(update_fields=["sha256", "verified_at"])
        self.url = reverse("file_download_url", args=[self.file.pk])
        self.adapter = Mock()
        self.adapter.stat_object.return_value = ObjectStat(size_bytes=12, version_id="verified-version-1")
        self.adapter.create_download_url.return_value = PresignedRequest(
            url="https://storage.example.invalid/fixture?signature=test-only", method="GET",
        )
        factory = patch("files.storage_adapters.get_storage_adapter", return_value=self.adapter)
        factory.start()
        self.addCleanup(factory.stop)

    def assert_no_authorization(self, status, **kwargs):
        self.assertEqual(self.client.get(self.url, **kwargs).status_code, status)
        self.adapter.create_download_url.assert_not_called()

    def test_plain_file_issues_private_url_without_reading_bytes_and_logs_only_authorization(self):
        self.file.file_name = "Báo cáo tháng 11.txt"
        self.file.save(update_fields=["file_name"])
        with patch("files.views._decrypt_file") as decrypt:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "presigned")
        self.assertEqual(response.json()["expires_in"], 180)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        decrypt.assert_not_called()
        self.adapter.open_object.assert_not_called()
        self.adapter.stat_object.assert_called_once_with(self.storage_location.object_ref, version_id="verified-version-1")
        self.adapter.create_download_url.assert_called_once_with(
            self.storage_location.object_ref, expires_in=180, download_name=self.file.file_name, version_id="verified-version-1",
        )
        event = ActivityLog.objects.get(action=ActivityLog.Action.DOWNLOAD)
        self.assertEqual(event.workspace_id, self.file.workspace_id)
        self.assertEqual(event.metadata["event"], "authorization_issued")
        self.assertNotIn("signature", str(event.metadata) + event.description)
        self.file.refresh_from_db()
        self.assertIsNotNone(self.file.last_accessed_at)

    def test_only_get_is_accepted(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)
        self.adapter.create_download_url.assert_not_called()

    def test_unauthenticated_and_other_user_are_denied(self):
        self.client.logout()
        self.assert_no_authorization(403)
        self.client.force_login(User.objects.create_user(username="unrelated-download"))
        self.assert_no_authorization(404)

    def test_membership_revocation_and_archived_workspace_are_denied(self):
        Membership.objects.filter(user=self.user).update(status=Membership.Status.REVOKED)
        self.assert_no_authorization(403)
        Membership.objects.filter(user=self.user).update(status=Membership.Status.ACTIVE)
        Workspace.objects.filter(pk=self.file.workspace_id).update(status=Workspace.Status.ARCHIVED)
        self.assert_no_authorization(404)

    def test_workspace_viewer_and_editor_can_download_until_membership_is_revoked(self):
        viewer = User.objects.create_user(username="workspace-download-viewer")
        membership = Membership.objects.create(tenant=self.file.tenant, user=viewer, role=Membership.Role.MEMBER)
        grant = WorkspaceMembership.objects.create(workspace=self.file.workspace, membership=membership, role="viewer")
        self.client.force_login(viewer)
        for role in ("viewer", "editor"):
            with self.subTest(role=role):
                grant.role, grant.status = role, WorkspaceMembership.Status.ACTIVE
                grant.save(update_fields=["role", "status"])
                self.assertEqual(self.client.get(self.url).json()["mode"], "presigned")
                self.adapter.reset_mock()
                grant.status = WorkspaceMembership.Status.REVOKED
                grant.save(update_fields=["status"])
                self.assert_no_authorization(404)

    def test_direct_share_revocation_prevents_new_authorization(self):
        recipient = User.objects.create_user(username="shared-download-viewer")
        share = Share.objects.create(tenant=self.file.tenant, owner=self.user, receiver=recipient, file=self.file)
        self.client.force_login(recipient)
        self.assertEqual(self.client.get(self.url).json()["mode"], "presigned")
        self.adapter.reset_mock()
        share.delete()
        self.assert_no_authorization(404)

    def test_explicit_workspace_selectors_must_match_and_agree(self):
        self.assert_no_authorization(404, HTTP_X_WORKSPACE_ID=str(self.user.personal_tenant.pk))
        self.assert_no_authorization(404, data={"workspace_id": "invalid"})
        response = self.client.get(self.url, HTTP_X_WORKSPACE_ID=str(self.file.workspace_id))
        self.assertEqual(response.status_code, 200)

    def test_unavailable_versions_locations_and_storage_are_denied(self):
        for state in FileVersion.State.values:
            if state == FileVersion.State.AVAILABLE:
                continue
            with self.subTest(state=state):
                FileVersion.objects.filter(pk=self.version.pk).update(state=state)
                self.assert_no_authorization(409)
        FileVersion.objects.filter(pk=self.version.pk).update(state="available")
        for state in (StorageLocation.State.ERROR, StorageLocation.State.DELETED):
            StorageLocation.objects.filter(pk=self.storage_location.pk).update(state=state)
            self.assert_no_authorization(409)
        StorageLocation.objects.filter(pk=self.storage_location.pk).update(state="available", object_ref="staging/" + "b" * 32)
        self.assert_no_authorization(409)
        StorageLocation.objects.filter(pk=self.storage_location.pk).update(object_ref=self.storage_location.object_ref)
        StorageConfig.objects.filter(pk=self.storage_config.pk).update(status="disabled")
        self.assert_no_authorization(409)

    def test_deleted_file_and_deleted_version_are_denied(self):
        FileVersion.objects.filter(pk=self.version.pk).update(deleted_at=timezone.now())
        self.assert_no_authorization(409)
        File.objects.filter(pk=self.file.pk).update(deleted_at=timezone.now())
        self.assert_no_authorization(404)

    def test_encryption_flags_and_metadata_never_issue_url(self):
        for model, key, value in [
            (self.file, "is_encrypted", True), (self.version, "is_encrypted", True),
            (self.version, "encryption_scheme", "aes-gcm"),
            (self.file, "wrapped_dek", b"legacy"), (self.version, "encryption_nonce", b"legacy"),
        ]:
            with self.subTest(model=type(model).__name__, key=key):
                original = getattr(model, key)
                setattr(model, key, value)
                model.save(update_fields=[key])
                self.assertEqual(self.client.get(self.url).json(), {"mode": "backend"})
                self.adapter.create_download_url.assert_not_called()
                setattr(model, key, original)
                model.save(update_fields=[key])
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.Action.DOWNLOAD).exists())

    def test_disabled_public_endpoint_and_legacy_files_use_backend(self):
        with override_settings(SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL=""):
            self.assertEqual(self.client.get(self.url).json(), {"mode": "backend"})
        self.storage_location.delete()
        self.version.delete()
        self.assertEqual(self.client.get(self.url).json(), {"mode": "backend"})
        self.adapter.create_download_url.assert_not_called()

    def test_missing_size_mismatch_and_provider_errors_fail_without_audit_success(self):
        self.adapter.stat_object.side_effect = StorageNotFoundError("missing")
        self.assert_no_authorization(404)
        self.adapter.stat_object.side_effect = None
        self.adapter.stat_object.return_value = ObjectStat(size_bytes=999)
        self.assert_no_authorization(422)
        self.adapter.stat_object.side_effect = RuntimeError("never expose provider details")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("provider details", response.content.decode())
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.Action.DOWNLOAD).exists())

    def test_storage_endpoint_mismatch_never_signs_another_provider(self):
        self.storage_config.endpoint = "https://another-store.example.invalid"
        self.storage_config.save(update_fields=["endpoint"])
        self.assert_no_authorization(503)

    def test_storage_cannot_return_a_different_version_even_with_matching_size(self):
        self.adapter.stat_object.return_value = ObjectStat(size_bytes=12, version_id="overwritten-v2")
        self.assert_no_authorization(422)

    def test_feature_flag_off_keeps_legacy_even_with_public_endpoint_configured(self):
        with override_settings(SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED=False):
            self.assertEqual(self.client.get(self.url).json(), {"mode": "backend"})
        self.adapter.stat_object.assert_not_called()
        self.adapter.create_download_url.assert_not_called()

    def test_cookie_scope_overlap_keeps_legacy_without_exposing_url(self):
        for values in [
            {"SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL": "http://testserver:9000"},
            {"SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL": "http://localhost:9000"},
            {"SESSION_COOKIE_DOMAIN": ".example.invalid"},
            {"CSRF_COOKIE_DOMAIN": ".example.invalid"},
        ]:
            with self.subTest(values=values), override_settings(**values):
                self.assertEqual(self.client.get(self.url).json(), {"mode": "backend"})
        self.adapter.create_download_url.assert_not_called()

    def test_unverified_primary_metadata_uses_legacy_content_verification(self):
        for model, key, value in [
            (self.version, "verified_at", None), (self.version, "sha256", ""),
            (self.storage_location, "verified_at", None), (self.storage_location, "checksum", "b" * 64),
            (self.storage_location, "provider_version_id", ""), (self.storage_location, "provider_version_id", "null"),
        ]:
            with self.subTest(key=key):
                original = getattr(model, key)
                setattr(model, key, value)
                model.save(update_fields=[key])
                self.assertEqual(self.client.get(self.url).json(), {"mode": "backend"})
                setattr(model, key, original)
                model.save(update_fields=[key])
        self.adapter.create_download_url.assert_not_called()

    def test_legacy_encrypted_download_really_decrypts_and_checks_hash(self):
        from security.aes_service import build_file_aad, encrypt_bytes, wrap_dek
        payload, master, dek = b"verified legacy bytes", b"m" * 32, b"d" * 32
        cipher, nonce = encrypt_bytes(payload, dek, build_file_aad(self.user.pk, self.file.pk, 1))
        wrapped, dek_nonce = wrap_dek(dek, master)
        self.version.is_encrypted = True
        self.version.encryption_nonce, self.version.wrapped_dek, self.version.dek_nonce = nonce, wrapped, dek_nonce
        self.version.sha256 = hashlib.sha256(payload).hexdigest()
        self.version.save(update_fields=["is_encrypted", "encryption_nonce", "wrapped_dek", "dek_nonce", "sha256"])
        self.assertEqual(self.client.get(self.url).json(), {"mode": "backend"})
        self.adapter.open_object.return_value = BytesIO(cipher)
        with patch("files.views.get_master_key", return_value=master):
            response = self.client.get(reverse("file_download", args=[self.file.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), payload)
        self.adapter.open_object.assert_called_once_with(self.storage_location.object_ref, version_id="verified-version-1")
        self.adapter.create_download_url.assert_not_called()
        self.assertTrue(ActivityLog.objects.filter(action=ActivityLog.Action.DECRYPT).exists())
        self.adapter.open_object.return_value = BytesIO(cipher[:-1] + bytes([cipher[-1] ^ 1]))
        with patch("files.views.get_master_key", return_value=master):
            response = self.client.get(reverse("file_download", args=[self.file.pk]), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 422)

    def test_client_cannot_choose_object_key_filename_or_expiry(self):
        response = self.client.get(self.url, {"object_key": "primary/" + "b" * 32, "filename": "evil.html", "expires_in": "9999"})
        self.assertEqual(response.status_code, 200)
        self.adapter.create_download_url.assert_called_once_with(self.storage_location.object_ref, expires_in=180, download_name=self.file.file_name, version_id="verified-version-1")
