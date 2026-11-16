"""Sprint 4.4: real team directory is a read-only view of workspaces."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import (
    Membership, PlatformAdminIdentity, Tenant, Workspace, WorkspaceMembership,
)
from accounts.services import get_personal_tenant


class AdminTeamDirectoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superadmin = User.objects.create_superuser(
            username="teams-super", email="teams-super@example.test", password="Strong-pass-123!",
        )
        self.platformadmin = User.objects.create_user(
            username="teams-platform", email="teams-platform@example.test",
            password="Strong-pass-123!", is_staff=True,
        )
        PlatformAdminIdentity.objects.create(
            user=self.platformadmin, invited_by=self.superadmin,
            status=PlatformAdminIdentity.Status.ACTIVE,
        )
        self.rogue_staff = User.objects.create_user(
            username="teams-rogue-staff", password="Strong-pass-123!", is_staff=True,
        )
        self.owner = User.objects.create_user(
            username="teams-owner", password="Strong-pass-123!",
        )
        self.viewer = User.objects.create_user(
            username="teams-viewer", password="Strong-pass-123!",
        )
        self.editor = User.objects.create_user(
            username="teams-editor", password="Strong-pass-123!",
        )
        self.inactive_user = User.objects.create_user(
            username="teams-inactive", password="Strong-pass-123!", is_active=False,
        )
        self.tenant = get_personal_tenant(self.owner)
        self.workspace = Workspace.objects.create(
            tenant=self.tenant, name="Blue Team", slug="blue-team", created_by=self.owner,
        )
        owner_membership = Membership.objects.get(tenant=self.tenant, user=self.owner)
        self._assign(owner_membership, "admin")
        self.viewer_membership = Membership.objects.create(
            tenant=self.tenant, user=self.viewer,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        self.viewer_assignment = self._assign(self.viewer_membership, "viewer")
        self.editor_membership = Membership.objects.create(
            tenant=self.tenant, user=self.editor,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        self.editor_assignment = self._assign(self.editor_membership, "editor")
        self.inactive_membership = Membership.objects.create(
            tenant=self.tenant, user=self.inactive_user,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        self._assign(self.inactive_membership, "viewer")
        self.business = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name="Acme Industries")
        self.business_workspace = Workspace.objects.create(
            tenant=self.business, name="Engineering", slug="engineering",
        )
        Workspace.objects.create(
            tenant=self.tenant, name="Archived", slug="archived",
            status=Workspace.Status.ARCHIVED,
        )
        self.suspended = Tenant.objects.create(
            kind=Tenant.Kind.BUSINESS, name="Suspended Corp",
            status=Tenant.Status.SUSPENDED,
        )
        Workspace.objects.create(tenant=self.suspended, name="Hidden", slug="hidden")
        self.url = reverse("api-admin-workspaces")
        self.client.force_login(self.superadmin)

    def _assign(self, membership, role):
        return WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=membership, role=role,
        )

    def _row(self, workspace=None):
        workspace = workspace or self.workspace
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        return next(row for row in response.json()["results"] if row["id"] == str(workspace.pk))

    def test_team_is_workspace_without_duplicate_team_model(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual({x["name"] for x in response.json()["results"]}, {"Blue Team", "Engineering"})
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertNotIn("file", response.json()["results"][0])

    def test_only_explicit_current_assignments_counted(self):
        row = self._row()
        self.assertEqual(row["created_by"], self.owner.username)
        self.assertEqual(row["member_count"], 3)
        self.assertEqual(row["role_counts"], {"admin": 1, "editor": 1, "viewer": 1})
        self.assertEqual(sum(row["role_counts"].values()), row["member_count"])

    def test_revocation_suspension_and_disabled_accounts_excluded(self):
        self.viewer_assignment.status = WorkspaceMembership.Status.REVOKED
        self.viewer_assignment.save(update_fields=["status"])
        self.editor_membership.status = Membership.Status.SUSPENDED
        self.editor_membership.save(update_fields=["status"])
        row = self._row()
        self.assertEqual(row["member_count"], 1)
        self.assertEqual(row["role_counts"], {"admin": 1, "editor": 0, "viewer": 0})

    def test_business_scope_and_empty_members(self):
        response = self.client.get(self.url, {"scope": "organization"})
        self.assertEqual(response.json()["count"], 1)
        row = response.json()["results"][0]
        self.assertEqual(row["scope"], "organization")
        self.assertEqual(row["organization"], "Acme Industries")
        self.assertEqual(row["member_count"], 0)
        self.assertEqual(row["role_counts"], {"admin": 0, "editor": 0, "viewer": 0})
        self.assertIsNone(row["created_by"])

    def test_personal_scope_and_name_or_organization_search(self):
        personal = self.client.get(self.url, {"scope": "personal", "q": "blue"}).json()
        self.assertEqual(personal["count"], 1)
        self.assertEqual(personal["results"][0]["id"], str(self.workspace.pk))
        org = self.client.get(self.url, {"q": "Acme"}).json()
        self.assertEqual(org["count"], 1)
        self.assertEqual(org["results"][0]["id"], str(self.business_workspace.pk))
        self.assertEqual(self.client.get(self.url, {"q": "Hidden"}).json()["count"], 0)

    def test_database_sort_and_filter_validation(self):
        ascending = self.client.get(self.url, {"sort": "name_asc"}).json()["results"]
        descending = self.client.get(self.url, {"sort": "name_desc"}).json()["results"]
        self.assertEqual([r["name"] for r in ascending], ["Blue Team", "Engineering"])
        self.assertEqual([r["name"] for r in descending], ["Engineering", "Blue Team"])
        self.assertEqual(self.client.get(self.url, {"scope": "bad"}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"sort": "secret"}).status_code, 400)

    def test_platform_admin_allowed_and_unregistered_staff_denied(self):
        self.client.force_login(self.platformadmin)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.force_login(self.rogue_staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_read_only_endpoint_rejects_writes(self):
        for method in ("post", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url, {}, content_type="application/json")
                self.assertEqual(response.status_code, 405)

    def test_pagination_counts_and_missing_page(self):
        for number in range(21):
            Workspace.objects.create(
                tenant=self.tenant, name=f"Group {number:02}", slug=f"group-{number:02}",
            )
        first = self.client.get(self.url, {"sort": "name_asc", "page": 1}).json()
        second = self.client.get(self.url, {"sort": "name_asc", "page": 2}).json()
        self.assertEqual(first["count"], 23)
        self.assertEqual(len(first["results"]), 20)
        self.assertEqual(len(second["results"]), 3)
        self.assertFalse(set(x["id"] for x in first["results"]) & set(x["id"] for x in second["results"]))
        self.assertEqual(self.client.get(self.url, {"page": 100}).json()["results"], [])
