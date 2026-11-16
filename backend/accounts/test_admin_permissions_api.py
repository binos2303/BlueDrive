"""Sprint 4.3: live read-only role directory (never the authority for grants)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import (
    Membership, PlatformAdminIdentity, Tenant, Workspace, WorkspaceMembership,
)
from accounts.services import get_personal_tenant

User = get_user_model()


class AdminPermissionsDirectoryTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(
            "roles-root", "roles-root@example.test", "Strong-pass-123!"
        )
        self.platformadmin = User.objects.create_user(
            "roles-operator", email="roles-operator@example.test",
            password="Strong-pass-123!", is_staff=True,
        )
        self.identity = PlatformAdminIdentity.objects.create(
            user=self.platformadmin, invited_by=self.superadmin,
            status=PlatformAdminIdentity.Status.ACTIVE,
        )
        self.owner = User.objects.create_user("roles-owner", password="Strong-pass-123!")
        self.viewer = User.objects.create_user("roles-viewer", password="Strong-pass-123!")
        self.editor = User.objects.create_user("roles-editor", password="Strong-pass-123!")
        self.tenant = get_personal_tenant(self.owner)
        self.workspace = Workspace.objects.create(
            tenant=self.tenant, name="Permissions Team", slug="permissions-team",
            created_by=self.owner,
        )
        owner_membership = Membership.objects.get(user=self.owner, tenant=self.tenant)
        WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=owner_membership,
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
        editor_membership = Membership.objects.create(
            user=self.editor, tenant=self.tenant,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=editor_membership,
            role=WorkspaceMembership.Role.EDITOR,
        )
        self.url = reverse("api-admin-permissions")

    def fetch_roles(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        return {row["id"]: row for row in response.json()["roles"]}

    def test_platform_admin_can_view_live_definitions_and_counts(self):
        for actor in (self.superadmin, self.platformadmin):
            self.client.force_login(actor)
            with self.subTest(actor=actor.username):
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Cache-Control"], "private, no-store")
                roles = {row["id"]: row for row in response.json()["roles"]}
                self.assertEqual(len(roles), 8)
                self.assertEqual(roles["super_admin"]["count"], 1)
                self.assertEqual(roles["platform_admin"]["count"], 1)
                self.assertEqual(roles["workspace_admin"]["count"], 1)
                self.assertEqual(roles["workspace_editor"]["count"], 1)
                self.assertEqual(roles["workspace_viewer"]["count"], 1)
                self.assertEqual(roles["workspace_viewer"]["count_unit"], "assignments")
                self.assertEqual(roles["super_admin"]["count_unit"], "accounts")
                for row in roles.values():
                    self.assertIsInstance(row["capabilities"], list)
                    self.assertGreaterEqual(row["count"], 0)

    def test_unprivileged_users_and_unregistered_staff_cannot_view(self):
        rogue_staff = User.objects.create_user(
            "unregistered-staff", password="Strong-pass-123!", is_staff=True,
        )
        for user in (self.owner, self.viewer, rogue_staff):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_only_real_roles_are_listed_not_demo_roles(self):
        self.client.force_login(self.superadmin)
        response = self.client.get(self.url)
        names = {row["label"] for row in response.json()["roles"]}
        self.assertNotIn("Infrastructure Manager", names)
        self.assertNotIn("Team Leader", names)
        self.assertNotIn("Auditor", names)
        self.assertIn("Workspace Viewer", names)
        self.assertIn("Tenant Owner", names)
        self.assertGreater(len(response.json()["notes"]), 0)

    def test_revoked_workspace_role_changes_count(self):
        self.client.force_login(self.superadmin)
        self.assertEqual(self.fetch_roles()["workspace_viewer"]["count"], 1)
        self.viewer_assignment.status = WorkspaceMembership.Status.REVOKED
        self.viewer_assignment.save(update_fields=["status", "updated_at"])
        self.assertEqual(self.fetch_roles()["workspace_viewer"]["count"], 0)

    def test_suspended_membership_and_archived_workspace_excluded(self):
        self.client.force_login(self.superadmin)
        self.viewer_membership.status = Membership.Status.SUSPENDED
        self.viewer_membership.save(update_fields=["status", "updated_at"])
        self.assertEqual(self.fetch_roles()["workspace_viewer"]["count"], 0)
        self.workspace.status = Workspace.Status.ARCHIVED
        self.workspace.save(update_fields=["status", "updated_at"])
        self.assertEqual(self.fetch_roles()["workspace_admin"]["count"], 0)
        self.assertEqual(self.fetch_roles()["workspace_editor"]["count"], 0)

    def test_disabled_platform_identity_removed_from_live_count(self):
        self.client.force_login(self.superadmin)
        self.assertEqual(self.fetch_roles()["platform_admin"]["count"], 1)
        self.identity.status = PlatformAdminIdentity.Status.DISABLED
        self.identity.save(update_fields=["status"])
        self.assertEqual(self.fetch_roles()["platform_admin"]["count"], 0)

    def test_permissions_directory_cannot_mutate_role_assignments(self):
        self.client.force_login(self.superadmin)
        response = self.client.post(self.url, {"role": "super_admin"})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(WorkspaceMembership.objects.filter(
            workspace=self.workspace, role=WorkspaceMembership.Role.ADMIN,
        ).count(), 1)
