"""Regression tests: platform workspace counts exclude internal/default areas."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.access import get_default_workspace
from accounts.models import Tenant, Workspace
from accounts.services import get_personal_tenant


class PlatformWorkspaceDirectoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.operator = User.objects.create_superuser(
            username="directory-operator", email="operator@example.test", password="test-secret-123!"
        )
        self.owner = User.objects.create_user(
            username="directory-user", email="user@example.test", password="test-secret-123!"
        )
        personal = get_personal_tenant(self.owner)
        self.default_personal = get_default_workspace(personal)
        self.personal_workspace = Workspace.objects.create(
            tenant=personal, name="test_workspace", slug="test-workspace", created_by=self.owner
        )
        self.archived = Workspace.objects.create(
            tenant=personal, name="Old Project", slug="old-project", status=Workspace.Status.ARCHIVED
        )
        self.business = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name="Example Corporation")
        self.default_business = get_default_workspace(self.business)
        self.business_workspace = Workspace.objects.create(
            tenant=self.business, name="Engineering", slug="engineering"
        )
        self.suspended = Tenant.objects.create(
            kind=Tenant.Kind.BUSINESS, name="Suspended Corp", status=Tenant.Status.SUSPENDED
        )
        self.suspended_workspace = Workspace.objects.create(
            tenant=self.suspended, name="Hidden Project", slug="hidden-project"
        )
        self.client.force_login(self.operator)

    def test_directory_returns_only_active_non_default_workspaces(self):
        response = self.client.get(reverse("api-admin-workspaces"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        rows = response.json()["results"]
        self.assertEqual(
            {row["id"] for row in rows},
            {str(self.personal_workspace.pk), str(self.business_workspace.pk)},
        )
        self.assertNotIn("is_default", rows[0])
        self.assertTrue(all(row["status"] == "active" for row in rows))

    def test_search_filters_after_excluding_defaults(self):
        result = self.client.get(reverse("api-admin-workspaces"), {"q": "General"}).json()
        self.assertEqual(result["count"], 0)
        result = self.client.get(reverse("api-admin-workspaces"), {"q": "test_workspace"}).json()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["id"], str(self.personal_workspace.pk))

    def test_overview_and_organization_counts_match_workspace_directory(self):
        summary = self.client.get(reverse("api-admin-overview"))
        self.assertEqual(summary.status_code, 200)
        workspaces = summary.json()["workspaces"]
        self.assertEqual(workspaces["total"], 2)
        self.assertEqual(workspaces["active"], 2)
        self.assertEqual(workspaces["personal"], 1)
        self.assertEqual(workspaces["organization"], 1)

        response = self.client.get(reverse("api-admin-organizations"))
        self.assertEqual(response.status_code, 200)
        counts = {row["name"]: row["workspaces"] for row in response.json()["results"]}
        self.assertEqual(counts["Example Corporation"], 1)
        self.assertEqual(counts["Suspended Corp"], 0)
