"""Super Admin file operations: lifecycle, authorization, audit and storage safety.

Run: python manage.py test accounts.test_admin_file_actions -v 2
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import (
    Membership, PlatformAdminAuditEvent, PlatformAdminIdentity, Tenant, Workspace,
)
from files.models import File, FileVersion
from files.permanent_delete import PermanentDeleteError
from folders.models import Folder


class AdminFileActionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superadmin = User.objects.create_superuser(
            username="root-audit", email="root@audit.test", password="strong-password-123!"
        )
        self.platformadmin = User.objects.create_user(
            username="file-operator", email="operator@audit.test", password="strong-password-123!",
            is_staff=True,
        )
        PlatformAdminIdentity.objects.create(
            user=self.platformadmin, invited_by=self.superadmin,
            status=PlatformAdminIdentity.Status.ACTIVE,
        )
        self.owner = User.objects.create_user(
            username="alice-files", email="alice@audit.test", password="strong-password-123!"
        )
        self.tenant = Tenant.objects.get(personal_owner=self.owner)
        self.workspace = Workspace.objects.get(tenant=self.tenant, is_default=True)
        self.file = File.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            file_name="Annual Report.PDF", file_size=1024, mime_type="application/pdf",
        )
        self.url = reverse("api-admin-file-action", args=[self.file.pk])
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.superadmin)
        csrf = self.client.get(reverse("api-csrf"))
        self.csrf_headers = {"HTTP_X_CSRFTOKEN": csrf.data["csrfToken"]}
        self.reason = "Data recovery request approved"

    def post_action(self, action, *, reason=None, confirmation=None, client=None, csrf=True):
        payload = {"action": action, "reason": self.reason if reason is None else reason}
        if action == "purge":
            payload["confirm_name"] = self.file.file_name if confirmation is None else confirmation
        headers = self.csrf_headers if csrf else {}
        return (client or self.client).post(self.url, payload, format="json", **headers)

    def test_superadmin_can_trash_then_restore_with_audit(self):
        moved = self.post_action("trash")
        self.assertEqual(moved.status_code, 200, moved.content)
        self.file.refresh_from_db()
        self.assertIsNotNone(self.file.deleted_at)
        self.assertEqual(self.post_action("trash").status_code, 409)
        restored = self.post_action("restore")
        self.assertEqual(restored.status_code, 200, restored.content)
        self.file.refresh_from_db()
        self.assertIsNone(self.file.deleted_at)
        self.assertIsNone(self.file.purge_after)
        self.assertEqual(self.post_action("restore").status_code, 409)
        self.assertEqual(list(PlatformAdminAuditEvent.objects.order_by("created_at").values_list("action", flat=True)), [
            PlatformAdminAuditEvent.Action.FILE_TRASH,
            PlatformAdminAuditEvent.Action.FILE_RESTORE,
        ])
        for event in PlatformAdminAuditEvent.objects.all():
            self.assertEqual(event.actor_id, self.superadmin.pk)
            self.assertEqual(event.target_user_id, self.owner.pk)
            self.assertEqual(event.metadata["file_id"], self.file.pk)
            self.assertNotIn("object_ref", event.metadata)

    def test_superadmin_only_for_writes_but_platformadmin_can_read_metadata(self):
        self.assertTrue(self.client.get(reverse("api-admin-files")).data["permissions"]["can_manage_files"])
        self.client.force_login(self.platformadmin)
        page = self.client.get(reverse("api-admin-files"))
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.data["permissions"]["can_manage_files"])
        self.assertEqual(self.post_action("trash").status_code, 403)
        self.assertEqual(PlatformAdminAuditEvent.objects.count(), 0)
        self.client.force_login(self.owner)
        self.assertEqual(self.post_action("trash").status_code, 403)
        self.assertEqual(self.client.get(reverse("api-admin-files")).status_code, 403)

    def test_csrf_and_strict_body_validation(self):
        self.assertEqual(self.post_action("trash", csrf=False).status_code, 403)
        self.assertEqual(self.post_action("trash", reason="short").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"action": "restore", "reason": self.reason, "extra": 2}, format="json", **self.csrf_headers).status_code, 400)
        self.assertEqual(self.post_action("unknown").status_code, 400)
        self.file.refresh_from_db()
        self.assertIsNone(self.file.deleted_at)
        self.assertFalse(PlatformAdminAuditEvent.objects.exists())

    def test_restore_prevents_live_name_collision(self):
        self.post_action("trash")
        File.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            file_name="annual report.pdf", file_size=10,
        )
        response = self.post_action("restore")
        self.assertEqual(response.status_code, 409, response.content)
        self.file.refresh_from_db()
        self.assertIsNotNone(self.file.deleted_at)
        self.assertEqual(PlatformAdminAuditEvent.objects.count(), 1)

    def test_restore_refuses_trashed_parent_folder(self):
        folder = Folder.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            folder_name="Old Folder", deleted_at=timezone.now(),
        )
        self.file.folder = folder
        self.file.deleted_at = timezone.now()
        self.file.save(update_fields=["folder", "deleted_at"])
        response = self.post_action("restore")
        self.assertEqual(response.status_code, 409, response.content)
        self.assertFalse(PlatformAdminAuditEvent.objects.exists())

    def test_trash_refuses_trashed_parent_folder(self):
        folder = Folder.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            folder_name="Old Folder", deleted_at=timezone.now(),
        )
        self.file.folder = folder
        self.file.save(update_fields=["folder"])
        response = self.post_action("trash")
        self.assertEqual(response.status_code, 409, response.content)
        self.assertFalse(PlatformAdminAuditEvent.objects.exists())

    def test_action_is_single_file_only(self):
        other = File.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            file_name="another-file.txt", file_size=100,
        )
        self.assertEqual(self.post_action("trash").status_code, 200)
        other.refresh_from_db()
        self.assertIsNone(other.deleted_at)

    def test_purge_refuses_live_files_or_wrong_confirmation(self):
        self.assertEqual(self.post_action("purge").status_code, 409)
        self.post_action("trash")
        self.assertEqual(self.post_action("purge", confirmation="annual report.pdf").status_code, 400)
        self.assertTrue(File.objects.filter(pk=self.file.pk).exists())
        self.assertFalse(PlatformAdminAuditEvent.objects.filter(action=PlatformAdminAuditEvent.Action.FILE_PURGE_REQUESTED).exists())

    def test_purge_reuses_cleanup_service_and_records_completion(self):
        self.file.deleted_at = timezone.now()
        self.file.save(update_fields=["deleted_at"])
        version = FileVersion.objects.create(
            tenant=self.tenant, file=self.file, version_number=1,
            size_bytes=1024, state=FileVersion.State.AVAILABLE,
        )
        response = self.post_action("purge")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(File.objects.filter(pk=self.file.pk).exists())
        self.assertFalse(FileVersion.objects.filter(pk=version.pk).exists())
        self.assertEqual(list(PlatformAdminAuditEvent.objects.order_by("created_at").values_list("action", flat=True)), [
            PlatformAdminAuditEvent.Action.FILE_PURGE_REQUESTED,
            PlatformAdminAuditEvent.Action.FILE_PURGE_SUCCEEDED,
        ])

    def test_failed_storage_cleanup_does_not_report_success(self):
        self.file.deleted_at = timezone.now()
        self.file.save(update_fields=["deleted_at"])
        with patch("accounts.admin_files_api.permanently_delete_files", side_effect=PermanentDeleteError("private/object/path")):
            response = self.post_action("purge")
        self.assertEqual(response.status_code, 503, response.content)
        self.assertTrue(File.objects.filter(pk=self.file.pk).exists())
        self.assertNotIn("private/object/path", response.content.decode())
        self.assertEqual(list(PlatformAdminAuditEvent.objects.order_by("created_at").values_list("action", flat=True)), [
            PlatformAdminAuditEvent.Action.FILE_PURGE_REQUESTED,
            PlatformAdminAuditEvent.Action.FILE_PURGE_FAILED,
        ])

    def test_missing_file_does_not_write_audit(self):
        response = self.client.post(reverse("api-admin-file-action", args=[99999999]), {
            "action": "trash", "reason": self.reason,
        }, format="json", **self.csrf_headers)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(PlatformAdminAuditEvent.objects.exists())

    def test_admin_audit_history_lists_file_actions(self):
        self.post_action("trash")
        audit = self.client.get(reverse("api-admin-audit"))
        self.assertEqual(audit.status_code, 200, audit.content)
        # The directory serializes only allowlisted details, not raw metadata.
        self.assertIn(PlatformAdminAuditEvent.Action.FILE_TRASH,
                      [event["action"] for event in audit.data["results"]])
        self.assertEqual(audit.data["results"][0]["resource_type"], "file")
        self.assertEqual(audit.data["results"][0]["resource_id"], self.file.pk)
        self.assertNotIn("file_id", audit.content.decode())
