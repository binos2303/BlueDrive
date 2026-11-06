"""Sprint 2.3: folder ZIP must honor permissions and include MinIO + legacy files."""
import base64
import hashlib
import io
import os
import tempfile
import zipfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.access import get_default_workspace
from accounts.models import Membership, WorkspaceMembership
from accounts.services import get_personal_tenant
from files.models import File, FileVersion, StorageConfig, StorageLocation
from folders.models import Folder
from logs.models import ActivityLog
from security.aes_service import (
    build_file_aad, encrypt_bytes, generate_dek, get_master_key, wrap_dek,
)
from sharing.models import Share

User = get_user_model()


class FolderArchiveDownloadTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("zip-owner", password="secret")
        self.viewer = User.objects.create_user("zip-viewer", password="secret")
        self.stranger = User.objects.create_user("zip-stranger", password="secret")
        self.tenant = get_personal_tenant(self.owner)
        self.workspace = get_default_workspace(self.tenant)
        self.folder = Folder.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            folder_name="Reports",
        )
        self.nested = Folder.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            parent=self.folder, folder_name="2026",
        )
        self.payload = b"primary-object-content"
        digest = hashlib.sha256(self.payload).hexdigest()
        self.file = File.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            folder=self.nested, file_name="report.txt", file_size=len(self.payload),
            mime_type="text/plain", hash_sha256=digest, is_encrypted=False,
        )
        self.version = FileVersion.objects.create(
            tenant=self.tenant, file=self.file, version_number=1,
            state=FileVersion.State.AVAILABLE, is_current=True,
            size_bytes=len(self.payload), mime_type="text/plain", sha256=digest,
            is_encrypted=False,
        )
        self.config = StorageConfig.objects.create(
            tenant=self.tenant, provider=StorageConfig.Provider.MINIO,
            status=StorageConfig.Status.ACTIVE,
        )
        StorageLocation.objects.create(
            tenant=self.tenant, file_version=self.version,
            storage_config=self.config, object_ref="primary/tests/zip-report",
            state=StorageLocation.State.AVAILABLE, size_bytes=len(self.payload),
        )
        self.client.force_login(self.owner)
        self.url = reverse("folder_download", args=[self.folder.pk])

    def _get_zip(self):
        with patch("files.storage_adapters.get_storage_adapter") as get_adapter:
            get_adapter.return_value.open_object.return_value = io.BytesIO(self.payload)
            response = self.client.get(self.url, HTTP_ACCEPT="application/zip, application/json")
        return response

    def _zip_entries(self, response):
        body = b"".join(response.streaming_content)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def test_minio_zip_contains_nested_files_and_empty_directories(self):
        Folder.objects.create(
            tenant=self.tenant, workspace=self.workspace,
            owner=self.owner, parent=self.folder, folder_name="Empty",
        )
        response = self._get_zip()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        entries = self._zip_entries(response)
        self.assertEqual(entries["Reports/2026/report.txt"], self.payload)
        self.assertIn("Reports/Empty/", entries)
        logs = ActivityLog.objects.filter(user=self.owner, action=ActivityLog.Action.DOWNLOAD)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().metadata["file_count"], 1)

    def test_external_direct_share_viewer_can_download_inherited_folder(self):
        Share.objects.create(
            tenant=self.tenant, owner=self.owner, receiver=self.viewer,
            folder=self.folder, permission=Share.Permission.VIEWER,
        )
        self.client.force_login(self.viewer)
        response = self._get_zip()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Reports/2026/report.txt", self._zip_entries(response))

    def test_workspace_member_viewer_can_download_without_direct_share(self):
        membership = Membership.objects.create(
            tenant=self.tenant, user=self.viewer,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=membership,
            role=WorkspaceMembership.Role.VIEWER,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        self.client.force_login(self.viewer)
        self.assertEqual(self._get_zip().status_code, 200)

    def test_workspace_archive_includes_folders_owned_by_other_members(self):
        Membership.objects.create(
            tenant=self.tenant, user=self.viewer,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        Folder.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.viewer,
            parent=self.folder, folder_name="Collaborator Empty",
        )
        entries = self._zip_entries(self._get_zip())
        self.assertIn("Reports/Collaborator Empty/", entries)

    def test_other_tenant_cannot_read_or_infer_folder(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self._get_zip().status_code, 404)
        self.assertFalse(ActivityLog.objects.filter(
            user=self.stranger, action=ActivityLog.Action.DOWNLOAD,
        ).exists())

    def test_trashed_folder_is_unavailable(self):
        from django.utils import timezone
        self.folder.deleted_at = timezone.now()
        self.folder.save(update_fields=["deleted_at"])
        self.assertEqual(self._get_zip().status_code, 404)

    def test_pending_scanning_file_blocks_entire_archive(self):
        self.version.state = FileVersion.State.SCANNING
        self.version.save(update_fields=["state"])
        with patch("files.storage_adapters.get_storage_adapter") as adapter:
            response = self.client.get(self.url, HTTP_ACCEPT="application/zip, application/json")
        self.assertEqual(response.status_code, 409)
        self.assertIn("detail", response.json())
        adapter.assert_not_called()
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.Action.DOWNLOAD).exists())

    def test_minio_checksum_mismatch_blocks_whole_archive(self):
        with patch("files.storage_adapters.get_storage_adapter") as adapter:
            adapter.return_value.open_object.return_value = io.BytesIO(b"corrupted")
            response = self.client.get(self.url, HTTP_ACCEPT="application/zip, application/json")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.Action.DOWNLOAD).exists())

    def test_missing_object_blocks_archive_without_success_log(self):
        with patch("files.storage_adapters.get_storage_adapter") as adapter:
            adapter.return_value.open_object.side_effect = FileNotFoundError("missing")
            response = self.client.get(self.url, HTTP_ACCEPT="application/zip, application/json")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.Action.DOWNLOAD).exists())

    def test_metadata_size_limit_blocks_before_storage_access(self):
        with patch("folders.archive_service.MAX_ARCHIVE_BYTES", len(self.payload) - 1):
            with patch("files.storage_adapters.get_storage_adapter") as adapter:
                response = self.client.get(self.url, HTTP_ACCEPT="application/zip, application/json")
        self.assertEqual(response.status_code, 413)
        adapter.assert_not_called()

    def test_zip_path_with_unsafe_component_is_rejected(self):
        self.nested.folder_name = "../escape"
        self.nested.save(update_fields=["folder_name"])
        response = self._get_zip()
        self.assertEqual(response.status_code, 422)
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.Action.DOWNLOAD).exists())

    def test_runtime_size_limit_rejects_underreported_content(self):
        self.file.file_size = 0
        self.file.save(update_fields=["file_size"])
        with patch("folders.archive_service.MAX_ARCHIVE_BYTES", len(self.payload) - 1):
            response = self._get_zip()
        self.assertEqual(response.status_code, 413)
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.Action.DOWNLOAD).exists())

    def test_missing_primary_location_blocks_archive(self):
        StorageLocation.objects.filter(file_version=self.version).update(
            state=StorageLocation.State.ERROR,
        )
        response = self._get_zip()
        self.assertEqual(response.status_code, 409)
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.Action.DOWNLOAD).exists())

    def test_deleted_child_file_is_absent_from_zip(self):
        from django.utils import timezone
        self.file.deleted_at = timezone.now()
        self.file.save(update_fields=["deleted_at"])
        response = self._get_zip()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Reports/2026/report.txt", self._zip_entries(response))

    def test_legacy_encrypted_file_is_included(self):
        with tempfile.TemporaryDirectory() as storage_dir, patch.dict(
            os.environ, {"SECUREDRIVE_AES_KEY": base64.b64encode(os.urandom(32)).decode()}
        ), override_settings(MEDIA_ROOT=storage_dir):
            plaintext = b"hello encrypted legacy"
            legacy = File.objects.create(
                tenant=self.tenant, workspace=self.workspace, owner=self.owner,
                folder=self.folder, file_name="legacy.txt", mime_type="text/plain",
                file_size=len(plaintext), hash_sha256=hashlib.sha256(plaintext).hexdigest(),
                is_encrypted=True, encryption_version=1,
            )
            dek = generate_dek()
            aad = build_file_aad(owner_id=self.owner.pk, file_id=legacy.pk, version=1)
            ciphertext, nonce = encrypt_bytes(plaintext, dek, aad)
            wrapped_dek, dek_nonce = wrap_dek(dek, get_master_key())
            legacy.file_path.save("legacy.bin", ContentFile(ciphertext), save=False)
            legacy.encryption_nonce = nonce
            legacy.wrapped_dek = wrapped_dek
            legacy.dek_nonce = dek_nonce
            legacy.save(update_fields=[
                "file_path", "encryption_nonce", "wrapped_dek", "dek_nonce", "updated_at",
            ])
            response = self._get_zip()
            self.assertEqual(response.status_code, 200)
            entries = self._zip_entries(response)
            self.assertEqual(entries["Reports/legacy.txt"], plaintext)
            self.assertEqual(entries["Reports/2026/report.txt"], self.payload)
