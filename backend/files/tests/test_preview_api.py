"""Sprint 2.2 regressions for the existing private file-view endpoint."""
from unittest.mock import patch

from cryptography.exceptions import InvalidTag
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.access import get_default_workspace
from accounts.models import Membership, WorkspaceMembership
from accounts.services import get_personal_tenant
from files.models import File, FileVersion
from logs.models import ActivityLog

User = get_user_model()


class PreviewApiRegressionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("preview-owner", password="secret")
        self.viewer = User.objects.create_user("preview-viewer", password="secret")
        self.stranger = User.objects.create_user("preview-stranger", password="secret")
        tenant = get_personal_tenant(self.owner)
        self.workspace = get_default_workspace(tenant)
        self.file = File.objects.create(
            tenant=tenant, workspace=self.workspace, owner=self.owner,
            file_name="notes.txt", file_path="uploads/legacy.txt",
            mime_type="text/plain", file_size=9,
        )
        self.url = reverse("file_view", args=[self.file.pk])
        self.client.force_login(self.owner)

    def test_owner_preview_is_inline_private_and_logged(self):
        with patch("files.views._decrypt_file", return_value=b"hello"):
            result = self.client.get(self.url, HTTP_ACCEPT="application/json, text/plain")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result["Content-Disposition"].startswith("inline;"))
        self.assertEqual(result["X-Content-Type-Options"], "nosniff")
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(b"".join(result.streaming_content), b"hello")
        self.assertEqual(ActivityLog.objects.filter(
            user=self.owner, action=ActivityLog.Action.VIEW,
        ).count(), 1)

    def test_private_file_in_other_tenant_is_not_previewable(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_workspace_viewer_can_preview_but_not_rename(self):
        membership = Membership.objects.create(
            tenant=self.file.tenant, user=self.viewer,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=membership,
            role=WorkspaceMembership.Role.VIEWER, status=WorkspaceMembership.Status.ACTIVE,
        )
        self.client.force_login(self.viewer)
        with patch("files.views._decrypt_file", return_value=b"readonly"):
            result = self.client.get(self.url)
        self.assertEqual(result.status_code, 200)

    def test_unsupported_pdf_cannot_be_previewed(self):
        self.file.mime_type = "application/pdf"
        self.file.save(update_fields=["mime_type"])
        with patch("files.views._decrypt_file") as decrypt:
            result = self.client.get(self.url, HTTP_ACCEPT="application/json")
        self.assertEqual(result.status_code, 409)
        decrypt.assert_not_called()

    def test_scanning_file_is_not_released(self):
        FileVersion.objects.create(
            tenant=self.file.tenant, file=self.file, version_number=1,
            is_current=True, state=FileVersion.State.SCANNING,
            size_bytes=self.file.file_size, mime_type=self.file.mime_type,
        )
        with patch("files.views._decrypt_file") as decrypt:
            result = self.client.get(self.url, HTTP_ACCEPT="application/json")
        self.assertEqual(result.status_code, 409)
        decrypt.assert_not_called()

    def test_integrity_failure_does_not_emit_view_activity(self):
        with patch("files.views._decrypt_file", side_effect=InvalidTag):
            result = self.client.get(self.url, HTTP_ACCEPT="application/json")
        self.assertEqual(result.status_code, 422)
        self.assertFalse(ActivityLog.objects.filter(
            user=self.owner, action=ActivityLog.Action.VIEW,
        ).exists())
