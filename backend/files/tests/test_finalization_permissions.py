"""Publication must honor permissions at commit, including changes during S3 I/O."""
import hashlib
import io
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection, DatabaseError
from django.test import TestCase, TransactionTestCase, override_settings

from accounts.models import Membership, QuotaAccount, Workspace, WorkspaceMembership
from files.models import File, QuotaReservation, UploadFinalizationJob, UploadSession
from files.services import unique_upload_name
from files.storage_adapters.base import MultipartUpload, ObjectStat, StorageAdapter
from folders.models import Folder
from rest_framework.test import APIClient


class FinalizationFixture:
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="publication-owner")
        self.editor = users.objects.create_user(username="publication-editor")
        self.tenant = self.owner.personal_tenant
        self.workspace = Workspace.objects.create(
            tenant=self.tenant, name="Publication", slug="publication", created_by=self.owner,
        )
        self.membership = Membership.objects.create(
            tenant=self.tenant, user=self.editor, role="member", status="active",
        )
        self.assignment = WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=self.membership, role="editor", status="active",
        )
        self.payload = b"verified publication fixture\n"
        self.adapter = Mock(spec=StorageAdapter)
        self.adapter.create_object_key.side_effect = lambda scope: scope + "/" + "a" * 32
        self.adapter.initiate_multipart.return_value = MultipartUpload("fixture-upload")
        for module in ("files.upload_api", "files.finalization", "files.management.commands.finalize_uploads"):
            self.enterContext(patch(f"{module}.get_storage_adapter", return_value=self.adapter))
        client = APIClient()
        client.force_authenticate(self.editor)
        response = client.post("/files/api/uploads/", {
            "name": "publication.txt", "size_bytes": len(self.payload),
            "sha256": hashlib.sha256(self.payload).hexdigest(),
        }, format="json", HTTP_X_WORKSPACE_ID=str(self.workspace.pk))
        self.assertEqual(response.status_code, 201, response.data)
        self.upload = UploadSession.objects.get(pk=response.data["upload_id"])
        response = client.post(f"/files/api/uploads/{self.upload.pk}/complete/", {
            "parts": [{"part_number": 1, "etag": "fixture-etag"}],
        }, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        stat = ObjectStat(size_bytes=len(self.payload), etag="fixture-etag", version_id="fixture-version",
                          metadata={"securedrive-upload-id": str(self.upload.pk)})
        self.adapter.complete_multipart.return_value = stat
        self.adapter.stat_object.return_value = stat
        self.adapter.publish_verified_object.return_value = stat
        self.adapter.put_object.return_value = stat

        def download(_key, destination, **kwargs):
            destination.write(self.payload)
            return stat

        self.adapter.download_to.side_effect = download


@override_settings(SECUREDRIVE_UPLOAD_SCANNER="")
class FinalizationPermissionTests(FinalizationFixture, TestCase):
    def assert_rejected(self):
        with self.assertLogs("files.management.commands.finalize_uploads", level="ERROR"):
            call_command("finalize_uploads", stdout=io.StringIO())
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.state, "failed")
        self.assertEqual(self.upload.failure_code, "destination_not_writable")
        self.assertEqual(UploadFinalizationJob.objects.get(upload_session=self.upload).state, "failed")
        self.assertFalse(File.objects.filter(workspace=self.workspace).exists())
        self.assertEqual(QuotaReservation.objects.get(upload_session=self.upload).state, "released")
        quota = QuotaAccount.objects.get(workspace=self.workspace, scope="workspace")
        self.assertEqual((quota.used_bytes, quota.reserved_bytes), (0, 0))

    def test_downgrade_before_copy_rejects_without_publication(self):
        self.assignment.role = "viewer"
        self.assignment.save(update_fields=["role"])
        self.assert_rejected()
        self.adapter.publish_verified_object.assert_not_called()

    def test_archive_before_copy_rejects_without_publication(self):
        self.workspace.status = "archived"
        self.workspace.save(update_fields=["status"])
        self.assert_rejected()
        self.adapter.publish_verified_object.assert_not_called()

    def test_revoked_tenant_member_cannot_publish(self):
        self.membership.status = "revoked"
        self.membership.save(update_fields=["status"])
        self.assert_rejected()
        self.adapter.publish_verified_object.assert_not_called()

    def test_deactivated_user_cannot_publish_with_stale_actor(self):
        get_user_model().objects.filter(pk=self.editor.pk).update(is_active=False)
        self.assert_rejected()
        self.adapter.publish_verified_object.assert_not_called()

    def test_role_change_during_copy_rejects_and_cleans_orphan(self):
        def downgrade(*args, **kwargs):
            WorkspaceMembership.objects.filter(pk=self.assignment.pk).update(role="viewer")
            return ObjectStat(size_bytes=len(self.payload), version_id="copy-version")

        self.adapter.publish_verified_object.side_effect = downgrade
        self.assert_rejected()
        self.upload.refresh_from_db()
        self.adapter.delete_object.assert_any_call(self.upload.final_object_key)

    def test_archive_during_copy_rejects_at_commit(self):
        def archive(*args, **kwargs):
            Workspace.objects.filter(pk=self.workspace.pk).update(status="archived")
            return ObjectStat(size_bytes=len(self.payload), version_id="copy-version")

        self.adapter.publish_verified_object.side_effect = archive
        self.assert_rejected()

    def test_trashed_folder_during_copy_cannot_receive_file(self):
        folder = Folder.objects.create(tenant=self.tenant, workspace=self.workspace, owner=self.owner, folder_name="Destination")
        UploadSession.objects.filter(pk=self.upload.pk).update(target_folder=folder)
        published = self.adapter.publish_verified_object.return_value

        def trash(*args, **kwargs):
            from django.utils import timezone
            Folder.objects.filter(pk=folder.pk).update(deleted_at=timezone.now())
            return published

        self.adapter.publish_verified_object.side_effect = trash
        self.assert_rejected()


@override_settings(SECUREDRIVE_UPLOAD_SCANNER="")
class FinalizationLockTests(FinalizationFixture, TransactionTestCase):
    serialized_rollback = True

    def test_permission_rows_stay_locked_at_commit_but_not_during_s3_copy(self):
        published = self.adapter.publish_verified_object.return_value

        def copy(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            return published

        self.adapter.publish_verified_object.side_effect = copy

        def check_locks(*args, **kwargs):
            other = connection.copy(alias="publication-lock-probe")
            try:
                other.ensure_connection()
                other.set_autocommit(True)
                rows = (self.upload, self.workspace, self.tenant, self.membership,
                        self.editor, self.assignment, UploadFinalizationJob.objects.get(upload_session=self.upload))
                with other.cursor() as cursor:
                    for row in rows:
                        table = other.ops.quote_name(row._meta.db_table)
                        with self.subTest(table=table):
                            with self.assertRaises(DatabaseError) as blocked:
                                cursor.execute(f"SELECT id FROM {table} WHERE id = %s FOR UPDATE NOWAIT", [row.pk])
                            self.assertEqual(blocked.exception.__cause__.sqlstate, "55P03")
            finally:
                other.close()
            return unique_upload_name(*args, **kwargs)

        with patch("files.finalization.unique_upload_name", side_effect=check_locks):
            call_command("finalize_uploads", stdout=io.StringIO())
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.state, "available")
        self.assertEqual(UploadFinalizationJob.objects.get(upload_session=self.upload).state, "done")
