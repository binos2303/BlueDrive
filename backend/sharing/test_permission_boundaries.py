"""Sprint 4.3: authorization boundaries across workspace, tenant and folder tree.

Run: python manage.py test sharing.test_permission_boundaries -v 2
"""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.access import can_access_workspace
from accounts.models import Membership, Workspace, WorkspaceMembership
from accounts.services import get_personal_tenant
from files.models import File
from folders.models import Folder
from sharing.models import Share
from sharing.services import (
    can_edit_file,
    can_edit_folder,
    can_view_file,
    can_view_folder,
    is_descendant_or_same,
)

User = get_user_model()


class WorkspacePermissionBoundaryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("role-owner", password="Strong-pass-123!")
        self.viewer = User.objects.create_user("role-viewer", password="Strong-pass-123!")
        self.editor = User.objects.create_user("role-editor", password="Strong-pass-123!")
        self.outsider = User.objects.create_user("role-outsider", password="Strong-pass-123!")
        self.platform_admin = User.objects.create_superuser(
            "platform-root-role", "platform-root@example.test", "Strong-pass-123!"
        )
        self.tenant = get_personal_tenant(self.owner)
        self.workspace = Workspace.objects.create(
            tenant=self.tenant, name="Team Workspace", slug="role-matrix-team",
            created_by=self.owner,
        )
        self.owner_membership = Membership.objects.get(user=self.owner, tenant=self.tenant)
        WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=self.owner_membership,
            role=WorkspaceMembership.Role.ADMIN,
        )
        self.viewer_membership = Membership.objects.create(
            user=self.viewer, tenant=self.tenant,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        self.viewer_assignment = WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=self.viewer_membership,
            role=WorkspaceMembership.Role.VIEWER,
        )
        self.editor_membership = Membership.objects.create(
            user=self.editor, tenant=self.tenant,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        self.editor_assignment = WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=self.editor_membership,
            role=WorkspaceMembership.Role.EDITOR,
        )
        self.parent = Folder.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            folder_name="Private Parent",
        )
        self.folder = Folder.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            parent=self.parent, folder_name="Team Docs",
        )
        self.file = File.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            folder=self.folder, file_name="sample.txt", file_size=8,
        )

    def file_details(self):
        return reverse("file_details", args=[self.file.pk])

    def folder_details(self):
        return reverse("folder_details", args=[self.folder.pk])

    def test_workspace_member_matrix(self):
        for user, can_view, can_edit in (
            (self.owner, True, True),
            (self.editor, True, True),
            (self.viewer, True, False),
            (self.outsider, False, False),
            (self.platform_admin, False, False),
        ):
            with self.subTest(user=user.username):
                self.assertEqual(can_view_file(self.file, user), can_view)
                self.assertEqual(can_edit_file(self.file, user), can_edit)
                self.assertEqual(can_view_folder(self.folder, user), can_view)
                self.assertEqual(can_edit_folder(self.folder, user), can_edit)

    def test_workspace_member_details_do_not_require_direct_share(self):
        for user, role, permission in (
            (self.viewer, "Workspace Viewer", "viewer"),
            (self.editor, "Workspace Editor", "editor"),
        ):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                file_response = self.client.get(self.file_details())
                self.assertEqual(file_response.status_code, 200)
                self.assertEqual(file_response["Cache-Control"], "private, no-store")
                self.assertEqual(file_response.json()["access"], role)
                self.assertEqual(file_response.json()["permission"], permission)
                self.assertEqual(file_response.json()["shared_by"], None)
                self.assertTrue(file_response.json()["location"].startswith(self.workspace.name))
                folder_response = self.client.get(self.folder_details())
                self.assertEqual(folder_response.status_code, 200)
                self.assertEqual(folder_response["Cache-Control"], "private, no-store")
                self.assertEqual(folder_response.json()["access"], role)
                self.assertEqual(folder_response.json()["permission"], permission)
                self.assertEqual(folder_response.json()["shared_by"], None)

    def test_cross_tenant_and_platform_admin_cannot_read_user_files(self):
        for user in (self.outsider, self.platform_admin):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertIn(self.client.get(self.file_details()).status_code, (403, 404))
                self.assertIn(self.client.get(self.folder_details()).status_code, (403, 404))

    def test_other_workspace_in_same_tenant_is_isolated(self):
        second = Workspace.objects.create(
            tenant=self.tenant, name="Other Workspace", slug="role-matrix-other",
            created_by=self.owner,
        )
        foreign_folder = Folder.objects.create(
            tenant=self.tenant, workspace=second, owner=self.owner,
            folder_name="Other Workspace Folder",
        )
        foreign_file = File.objects.create(
            tenant=self.tenant, workspace=second, owner=self.owner,
            folder=foreign_folder, file_name="other.txt",
        )
        self.assertFalse(can_access_workspace(self.viewer, second))
        self.assertFalse(can_view_file(foreign_file, self.viewer))
        self.assertFalse(can_view_folder(foreign_folder, self.viewer))
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("file_details", args=[foreign_file.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("folder_details", args=[foreign_folder.pk])).status_code, 404)

    def test_revoked_workspace_role_is_effective_immediately(self):
        self.assertTrue(can_view_file(self.file, self.viewer))
        self.viewer_assignment.status = WorkspaceMembership.Status.REVOKED
        self.viewer_assignment.save(update_fields=["status", "updated_at"])
        self.assertFalse(can_view_file(self.file, self.viewer))
        self.assertFalse(can_view_folder(self.folder, self.viewer))
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.file_details()).status_code, 404)

    def test_suspended_tenant_membership_blocks_workspace_role(self):
        self.editor_membership.status = Membership.Status.SUSPENDED
        self.editor_membership.save(update_fields=["status", "updated_at"])
        self.assertFalse(can_edit_file(self.file, self.editor))
        self.assertFalse(can_view_file(self.file, self.editor))
        self.assertFalse(can_view_folder(self.folder, self.editor))

    def test_archived_workspace_blocks_access(self):
        self.workspace.status = Workspace.Status.ARCHIVED
        self.workspace.save(update_fields=["status", "updated_at"])
        for user in (self.owner, self.viewer, self.editor):
            with self.subTest(user=user.username):
                self.assertFalse(can_view_file(self.file, user))
                self.assertFalse(can_view_folder(self.folder, user))
                self.assertFalse(can_edit_file(self.file, user))

    def test_deleted_ancestor_blocks_live_child_even_for_workspace_admin(self):
        self.parent.deleted_at = timezone.now()
        self.parent.save(update_fields=["deleted_at"])
        self.assertIsNone(self.folder.deleted_at)
        self.assertIsNone(self.file.deleted_at)
        for user in (self.owner, self.viewer, self.editor):
            with self.subTest(user=user.username):
                self.assertFalse(can_view_file(self.file, user))
                self.assertFalse(can_edit_file(self.file, user))
                self.assertFalse(can_view_folder(self.folder, user))
                self.assertFalse(can_edit_folder(self.folder, user))
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.file_details()).status_code, 404)
                self.assertEqual(self.client.get(self.folder_details()).status_code, 404)

    def test_deleted_ancestor_blocks_direct_share(self):
        Share.objects.create(
            tenant=self.tenant, owner=self.owner, receiver=self.outsider,
            file=self.file, permission=Share.Permission.EDITOR,
        )
        self.assertTrue(can_edit_file(self.file, self.outsider))
        self.parent.deleted_at = timezone.now()
        self.parent.save(update_fields=["deleted_at"])
        self.assertFalse(can_view_file(self.file, self.outsider))
        self.assertFalse(can_edit_file(self.file, self.outsider))
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.file_details()).status_code, 404)

    def test_direct_file_share_does_not_disclose_owner_folder_path(self):
        Share.objects.create(
            tenant=self.tenant, owner=self.owner, receiver=self.outsider,
            file=self.file, permission=Share.Permission.VIEWER,
        )
        self.client.force_login(self.outsider)
        result = self.client.get(self.file_details())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["location"], "Shared with me")
        self.assertEqual(result.json()["access"], "Viewer")
        self.assertEqual(result.json()["permission"], "viewer")
        self.assertNotIn(self.parent.folder_name, result.content.decode())

    def test_direct_folder_share_only_reveals_shared_subtree(self):
        Share.objects.create(
            tenant=self.tenant, owner=self.owner, receiver=self.outsider,
            folder=self.folder, permission=Share.Permission.VIEWER,
        )
        self.client.force_login(self.outsider)
        result = self.client.get(self.file_details())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["location"], "Shared with me")
        folder_details = self.client.get(self.folder_details())
        self.assertEqual(folder_details.status_code, 200)
        self.assertEqual(folder_details.json()["ancestors"], [])

    def test_malformed_parent_workspace_is_denied(self):
        alien_tenant = get_personal_tenant(self.outsider)
        alien_workspace = Workspace.objects.get(tenant=alien_tenant, is_default=True)
        alien_folder = Folder.objects.create(
            tenant=alien_tenant, workspace=alien_workspace,
            owner=self.outsider, folder_name="Alien Folder",
        )
        # PostgreSQL correctly forbids persisting a File that points at a folder
        # from another tenant/workspace (composite FKs, checked at test teardown).
        # Simulate a malformed loaded object in memory to test defense in depth.
        self.file.folder = alien_folder
        self.assertFalse(can_view_file(self.file, self.owner))
        self.assertFalse(can_edit_file(self.file, self.owner))
        self.assertFalse(can_view_file(self.file, self.editor))

        # Exercise the HTTP authorization path using the malformed object,
        # without violating database integrity constraints.
        with patch("files.views.get_object_or_404", return_value=self.file):
            for user in (self.owner, self.editor):
                with self.subTest(user=user.username):
                    self.client.force_login(user)
                    self.assertEqual(self.client.get(self.file_details()).status_code, 404)

        # The actual persisted relationship must remain valid and unchanged.
        self.file.refresh_from_db()
        self.assertEqual(self.file.folder_id, self.folder.pk)


    def rename(self, user, *, item_id=None, header_workspace=None):
        self.client.force_login(user)
        payload = {
            "kind": "file", "id": self.file.pk if item_id is None else item_id,
            "name": "renamed-by-role.txt", "workspace_id": str(self.workspace.pk),
        }
        headers = {} if header_workspace is None else {"HTTP_X_WORKSPACE_ID": str(header_workspace)}
        return self.client.post(
            reverse("drive_items_rename_api"), json.dumps(payload),
            content_type="application/json", **headers,
        )

    def test_rename_api_enforces_workspace_editor_boundary(self):
        denied = self.rename(self.viewer)
        self.assertEqual(denied.status_code, 403)
        self.file.refresh_from_db()
        self.assertEqual(self.file.file_name, "sample.txt")
        allowed = self.rename(self.editor)
        self.assertEqual(allowed.status_code, 200, allowed.content)
        self.file.refresh_from_db()
        self.assertEqual(self.file.file_name, "renamed-by-role.txt")

    def test_rename_api_rejects_cross_workspace_object_id(self):
        other = Workspace.objects.create(
            tenant=self.tenant, name="Foreign Context", slug="role-matrix-context",
            created_by=self.owner,
        )
        other_file = File.objects.create(
            tenant=self.tenant, workspace=other, owner=self.owner,
            file_name="foreign-context.txt",
        )
        response = self.rename(self.editor, item_id=other_file.pk)
        self.assertEqual(response.status_code, 404)
        other_file.refresh_from_db()
        self.assertEqual(other_file.file_name, "foreign-context.txt")

    def test_conflicting_workspace_header_and_body_fail_closed(self):
        unrelated = Workspace.objects.create(
            tenant=self.tenant, name="Header Conflict", slug="role-matrix-header",
            created_by=self.owner,
        )
        response = self.rename(self.owner, header_workspace=unrelated.pk)
        self.assertEqual(response.status_code, 404)
        self.file.refresh_from_db()
        self.assertEqual(self.file.file_name, "sample.txt")

    def test_editor_cannot_rename_child_of_trashed_parent(self):
        self.parent.deleted_at = timezone.now()
        self.parent.save(update_fields=["deleted_at"])
        response = self.rename(self.editor)
        self.assertEqual(response.status_code, 403)
        self.file.refresh_from_db()
        self.assertEqual(self.file.file_name, "sample.txt")

    def test_folder_cycle_fails_closed_without_infinite_loop(self):
        self.parent.parent = self.folder
        self.parent.save(update_fields=["parent"])
        self.assertFalse(can_view_file(self.file, self.owner))
        self.assertFalse(can_edit_folder(self.folder, self.editor))
        unrelated = Folder.objects.create(
            tenant=self.tenant, workspace=self.workspace,
            owner=self.owner, folder_name="Unrelated Folder",
        )
        self.assertFalse(is_descendant_or_same(self.folder, unrelated))
