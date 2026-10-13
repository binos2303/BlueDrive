from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from accounts.models import QuotaAccount, Tenant
from files.models import File, FileVersion, UploadSession
from files.serializers import (
    FileMetadataSerializer,
    FileVersionMetadataSerializer,
    QuotaUsageSerializer,
    UploadSessionStatusSerializer,
)
from folders.models import Folder
from folders.serializers import FolderMetadataSerializer


User = get_user_model()


class TenantModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tenant-user")
        self.tenant = self.user.personal_tenant
        self.other_user = User.objects.create_user(username="other-tenant-user")
        self.other_tenant = self.other_user.personal_tenant

    def test_folder_live_names_are_case_insensitive_and_trash_can_reuse_name(self):
        live = Folder.objects.create(
            tenant=self.tenant,
            owner=self.user,
            folder_name="Projects",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Folder.objects.create(
                    tenant=self.tenant,
                    owner=self.user,
                    folder_name="projects",
                )

        trashed = Folder.objects.create(
            tenant=self.tenant,
            owner=self.user,
            folder_name="projects",
            deleted_at="2030-01-01T00:00:00Z",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Folder.objects.filter(pk=trashed.pk).update(deleted_at=None)
        self.assertIsNone(Folder.objects.get(pk=live.pk).deleted_at)
        self.assertIsNotNone(Folder.objects.get(pk=trashed.pk).deleted_at)

    def test_file_live_names_are_unique_per_tenant_and_folder(self):
        File.objects.create(
            tenant=self.tenant,
            owner=self.user,
            file_name="report.pdf",
            file_path="uploads/report.enc",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                File.objects.create(
                    tenant=self.tenant,
                    owner=self.user,
                    file_name="REPORT.PDF",
                    file_path="uploads/report-2.enc",
                )

    def test_serializers_expose_metadata_only_and_are_read_only(self):
        folder = Folder.objects.create(
            tenant=self.tenant,
            owner=self.user,
            folder_name="Documents",
        )
        drive_file = File.objects.create(
            tenant=self.tenant,
            owner=self.user,
            folder=folder,
            file_name="encrypted.bin",
            file_path="uploads/secret-key.enc",
            wrapped_dek=b"not-for-api",
            encryption_nonce=b"nonce",
            dek_nonce=b"dek-nonce",
        )
        version = FileVersion.objects.create(
            tenant=self.tenant,
            file=drive_file,
            version_number=1,
            state=FileVersion.State.PENDING,
            size_bytes=drive_file.file_size,
            wrapped_dek=b"not-for-api",
        )
        upload = UploadSession.objects.create(
            tenant=self.tenant,
            initiated_by=self.user,
            client_name="queued.bin",
            expected_size_bytes=10,
            expires_at="2030-01-01T00:00:00Z",
        )

        file_data = FileMetadataSerializer(drive_file).data
        folder_data = FolderMetadataSerializer(folder).data
        version_data = FileVersionMetadataSerializer(version).data
        upload_data = UploadSessionStatusSerializer(upload).data

        self.assertNotIn("file_path", file_data)
        self.assertNotIn("tenant", file_data)
        self.assertNotIn("owner", file_data)
        self.assertNotIn("wrapped_dek", file_data)
        self.assertNotIn("encryption_nonce", file_data)
        self.assertNotIn("dek_nonce", file_data)
        self.assertNotIn("tenant", folder_data)
        self.assertNotIn("owner", folder_data)
        self.assertEqual(set(file_data.keys()), set(FileMetadataSerializer.Meta.fields))
        self.assertTrue(all(FileMetadataSerializer().fields[name].read_only for name in FileMetadataSerializer.Meta.fields))
        self.assertTrue(all(FolderMetadataSerializer().fields[name].read_only for name in FolderMetadataSerializer.Meta.fields))
        self.assertIn("used_bytes", QuotaUsageSerializer.Meta.fields)
        self.assertNotIn("user", QuotaUsageSerializer.Meta.fields)
        self.assertNotIn("tenant", QuotaUsageSerializer.Meta.fields)
        self.assertNotIn("wrapped_dek", version_data)
        self.assertNotIn("sha256", FileVersionMetadataSerializer.Meta.fields)
        self.assertNotIn("tenant", upload_data)
        self.assertNotIn("initiated_by", upload_data)
        self.assertNotIn("target_folder", upload_data)
        self.assertNotIn("expected_sha256", upload_data)

    @skipUnless(connection.vendor == "postgresql", "Composite foreign keys are PostgreSQL-only.")
    def test_postgres_rejects_cross_tenant_parent_and_file_folder(self):
        parent = Folder.objects.create(
            tenant=self.tenant,
            owner=self.user,
            folder_name="Parent",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Folder.objects.create(
                    tenant=self.other_tenant,
                    owner=self.other_user,
                    folder_name="Wrong parent",
                    parent=parent,
                )
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

        other_folder = Folder.objects.create(
            tenant=self.other_tenant,
            owner=self.other_user,
            folder_name="Other folder",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                File.objects.create(
                    tenant=self.tenant,
                    owner=self.user,
                    folder=other_folder,
                    file_name="cross-tenant.txt",
                    file_path="uploads/cross.enc",
                )
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
