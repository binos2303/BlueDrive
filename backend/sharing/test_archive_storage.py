import base64
import hashlib
import io
import os
import tempfile
import zipfile
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.access import get_default_workspace
from files.models import File, FileVersion, StorageConfig, StorageLocation
from security.aes_service import build_file_aad, encrypt_bytes, generate_dek, get_master_key, wrap_dek
from sharing.models import Share


class SharedArchiveStorageTests(TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(self.settings(MEDIA_ROOT=directory))
        self.enterContext(patch.dict(os.environ, {"SECUREDRIVE_AES_KEY": base64.b64encode(os.urandom(32)).decode()}))
        self.owner = get_user_model().objects.create_user(username="archive-owner")
        self.receiver = get_user_model().objects.create_user(username="archive-reader")
        self.workspace = get_default_workspace(self.owner.personal_tenant)
        self.client.force_login(self.receiver)

    def shared_file(self, name, payload):
        file = File.objects.create(tenant=self.owner.personal_tenant, workspace=self.workspace, owner=self.owner,
            file_name=name, file_size=len(payload), hash_sha256=hashlib.sha256(payload).hexdigest())
        Share.objects.create(tenant=file.tenant, owner=self.owner, receiver=self.receiver, file=file)
        return file

    def s3_file(self, payload):
        file = self.shared_file("stored.txt", payload)
        version = FileVersion.objects.create(tenant=file.tenant, file=file, version_number=1, state="available",
            is_current=True, size_bytes=len(payload), sha256=file.hash_sha256, verified_at=timezone.now())
        config = StorageConfig.objects.create(tenant=file.tenant, provider="s3")
        location = StorageLocation.objects.create(tenant=file.tenant, file_version=version, storage_config=config,
            object_ref="primary/" + "c" * 32, state="available", size_bytes=len(payload), checksum=file.hash_sha256,
            provider_version_id="archive-verified-version")
        return file, location

    def test_zip_reads_version_pinned_s3_and_legacy_aes_with_same_reader(self):
        payload = b"object storage contents\n"
        file, location = self.s3_file(payload)
        legacy_payload = b"legacy encrypted contents\n"
        legacy = self.shared_file("legacy.txt", legacy_payload)
        dek = generate_dek()
        ciphertext, nonce = encrypt_bytes(legacy_payload, dek, build_file_aad(legacy.owner_id, legacy.pk, 1))
        wrapped, dek_nonce = wrap_dek(dek, get_master_key())
        legacy.file_path.save("legacy.enc", ContentFile(ciphertext), save=False)
        legacy.is_encrypted, legacy.encryption_nonce = True, nonce
        legacy.wrapped_dek, legacy.dek_nonce = wrapped, dek_nonce
        legacy.save()
        adapter = Mock()
        adapter.open_object.return_value = io.BytesIO(payload)
        with patch("files.storage_adapters.get_storage_adapter", return_value=adapter):
            response = self.client.post(reverse("bulk_download_shared"), {"file_ids": [file.pk, legacy.pk]})
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as archive:
                self.assertEqual(archive.read("stored.txt"), payload)
                self.assertEqual(archive.read("legacy.txt"), legacy_payload)
            response.close()
        adapter.open_object.assert_called_once_with(location.object_ref, version_id="archive-verified-version")

    def test_bad_hash_or_missing_permission_blocks_entire_archive(self):
        file, _ = self.s3_file(b"expected bytes")
        adapter = Mock()
        adapter.open_object.return_value = io.BytesIO(b"corrupt bytes")
        with patch("files.storage_adapters.get_storage_adapter", return_value=adapter):
            response = self.client.post(reverse("bulk_download_shared"), {"file_ids": [file.pk]})
        self.assertEqual(response.status_code, 302)
        Share.objects.filter(file=file).delete()
        with patch("files.storage_adapters.get_storage_adapter") as factory:
            response = self.client.post(reverse("bulk_download_shared"), {"file_ids": [file.pk]})
        self.assertEqual(response.status_code, 302)
        factory.assert_not_called()
