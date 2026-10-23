"""Regression tests for workspace-scoped Drive access and mutations."""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.access import can_access_workspace, can_edit_workspace_content
from accounts.models import Membership, Tenant, Workspace, WorkspaceMembership
from files.models import File, UploadSession
from folders.models import Folder
from sharing.services import can_edit_file, can_view_file


User = get_user_model()


class WorkspaceDriveAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(
            username="workspace-owner",
            email="workspace-owner@example.test",
            password="test-password",
        )
        self.tenant = Tenant.objects.create(
            kind=Tenant.Kind.BUSINESS,
            name="Workspace Access Corporation",
        )
        self.owner_membership = Membership.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role=Membership.Role.OWNER,
            status=Membership.Status.ACTIVE,
        )
        self.member = User.objects.create_user(
            username="workspace-member",
            email="workspace-member@example.test",
            password="test-password",
        )
        self.member_membership = Membership.objects.create(
            tenant=self.tenant,
            user=self.member,
            role=Membership.Role.MEMBER,
            status=Membership.Status.ACTIVE,
        )

        self.default_workspace = Workspace.objects.get(
            tenant=self.tenant,
            is_default=True,
        )
        self.viewer_workspace = Workspace.objects.create(
            tenant=self.tenant,
            name="Read Only",
            slug="read-only",
        )
        self.private_workspace = Workspace.objects.create(
            tenant=self.tenant,
            name="Restricted",
            slug="restricted",
        )
        WorkspaceMembership.objects.create(
            workspace=self.viewer_workspace,
            membership=self.member_membership,
            role=WorkspaceMembership.Role.VIEWER,
            status=WorkspaceMembership.Status.ACTIVE,
        )

        self.default_file = self._create_file(
            self.default_workspace,
            "general.txt",
        )
        self.viewer_file = self._create_file(
            self.viewer_workspace,
            "read-only.txt",
        )
        self.private_file = self._create_file(
            self.private_workspace,
            "restricted.txt",
        )
        self.client.force_login(self.member)

    def _create_file(self, workspace, name):
        return File.objects.create(
            tenant=self.tenant,
            workspace=workspace,
            owner=self.member,
            file_name=name,
            file_path=f"uploads/{workspace.slug}-{name}.enc",
            file_size=12,
            mime_type="text/plain",
        )

    def test_workspace_viewer_can_read_owned_file_but_cannot_edit(self):
        self.assertTrue(can_access_workspace(self.member, self.viewer_workspace))
        self.assertTrue(can_view_file(self.viewer_file, self.member))
        self.assertFalse(can_edit_workspace_content(self.member, self.viewer_workspace))
        self.assertFalse(can_edit_file(self.viewer_file, self.member))

    def test_drive_list_returns_only_items_from_selected_workspace(self):
        response = self.client.get(
            reverse("drive_items_api"),
            {"workspace_id": str(self.viewer_workspace.pk)},
        )

        self.assertEqual(response.status_code, 200)
        names = {item["name"] for item in response.json()["items"]}
        self.assertEqual(names, {"read-only.txt"})

    def test_legacy_default_context_does_not_leak_other_workspace_items(self):
        response = self.client.get(reverse("drive_items_api"))

        self.assertEqual(response.status_code, 200)
        names = {item["name"] for item in response.json()["items"]}
        self.assertIn("general.txt", names)
        self.assertNotIn("read-only.txt", names)
        self.assertNotIn("restricted.txt", names)

    def test_explicit_workspace_without_membership_is_not_fallback_to_default(self):
        response = self.client.get(
            reverse("drive_items_api"),
            {"workspace_id": str(self.private_workspace.pk)},
        )
        self.assertEqual(response.status_code, 404)

    def test_viewer_cannot_create_root_folder_in_read_only_workspace(self):
        response = self.client.post(
            reverse("folder_create_api"),
            data=json.dumps({
                "name": "Not Allowed",
                "workspace_id": str(self.viewer_workspace.pk),
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Folder.objects.filter(
            tenant=self.tenant,
            workspace=self.viewer_workspace,
            folder_name="Not Allowed",
        ).exists())

    def test_viewer_cannot_start_upload_in_read_only_workspace(self):
        before = UploadSession.objects.count()
        response = self.client.post(
            reverse("api-upload-create"),
            data=json.dumps({
                "name": "not-allowed.txt",
                "size_bytes": 1,
                "sha256": "0" * 64,
                "workspace_id": str(self.viewer_workspace.pk),
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(UploadSession.objects.count(), before)

    def test_move_api_cannot_select_an_item_from_another_workspace(self):
        response = self.client.post(
            reverse("drive_items_move_api"),
            data=json.dumps({
                "workspace_id": str(self.default_workspace.pk),
                "file_ids": [self.private_file.pk],
                "folder_ids": [],
                "destination_folder_id": None,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        self.private_file.refresh_from_db()
        self.assertIsNone(self.private_file.folder_id)

    def test_archived_workspace_denies_owner_access(self):
        self.viewer_workspace.status = Workspace.Status.ARCHIVED
        self.viewer_workspace.save(update_fields=["status", "updated_at"])

        self.assertFalse(can_access_workspace(self.member, self.viewer_workspace))
        self.assertFalse(can_view_file(self.viewer_file, self.member))
        response = self.client.get(
            reverse("drive_items_api"),
            {"workspace_id": str(self.viewer_workspace.pk)},
        )
        self.assertEqual(response.status_code, 404)
