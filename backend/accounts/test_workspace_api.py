from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.access import workspace_role_for_user
from accounts.models import Membership, Tenant, Workspace, WorkspaceMembership
from logs.models import ActivityLog

User = get_user_model()


class WorkspaceApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(username="org-admin", password="test-password")
        self.member = User.objects.create_user(username="org-member", password="test-password")
        self.tenant = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name="Example Corporation")
        self.admin_membership = Membership.objects.create(
            tenant=self.tenant, user=self.admin,
            role=Membership.Role.ADMIN, status=Membership.Status.ACTIVE,
        )
        self.member_membership = Membership.objects.create(
            tenant=self.tenant, user=self.member,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        self.client.force_authenticate(self.admin)

    def test_admin_can_create_workspace_and_creator_is_admin(self):
        response = self.client.post(
            reverse("api-organization-workspaces", args=[self.tenant.pk]),
            {"name": "Engineering", "description": "Engineering documents"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        workspace = Workspace.objects.get(pk=response.data["workspace"]["id"])
        assignment = WorkspaceMembership.objects.get(
            workspace=workspace, membership=self.admin_membership,
        )
        self.assertEqual(assignment.role, WorkspaceMembership.Role.ADMIN)
        self.assertTrue(ActivityLog.objects.filter(
            tenant=self.tenant, user=self.admin,
            action=ActivityLog.Action.CREATE_WORKSPACE,
        ).exists())

    def test_regular_member_cannot_create_workspace(self):
        self.client.force_authenticate(self.member)
        response = self.client.post(
            reverse("api-organization-workspaces", args=[self.tenant.pk]),
            {"name": "Unauthorized"}, format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_access_requires_direct_workspace_membership(self):
        workspace = Workspace.objects.create(
            tenant=self.tenant, name="Engineering", slug="engineering",
        )
        self.assertIsNone(workspace_role_for_user(self.member, workspace))
        assignment = WorkspaceMembership.objects.create(
            workspace=workspace,
            membership=self.member_membership,
            role=WorkspaceMembership.Role.EDITOR,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        self.assertEqual(workspace_role_for_user(self.member, workspace), WorkspaceMembership.Role.EDITOR)
        assignment.status = WorkspaceMembership.Status.REVOKED
        assignment.save(update_fields=["status", "updated_at"])
        self.assertIsNone(workspace_role_for_user(self.member, workspace))

    def test_workspace_access_does_not_cross_tenants(self):
        other_tenant = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name="Other Corporation")
        workspace = Workspace.objects.create(
            tenant=other_tenant, name="Finance", slug="finance",
        )
        self.assertIsNone(workspace_role_for_user(self.member, workspace))
        response = self.client.get(
            reverse("api-workspace-members", args=[other_tenant.pk, workspace.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_owner_or_tenant_admin_has_workspace_admin_role(self):
        workspace = Workspace.objects.create(tenant=self.tenant, name="Finance", slug="finance")
        self.assertEqual(workspace_role_for_user(self.admin, workspace), WorkspaceMembership.Role.ADMIN)
        workspace.status = Workspace.Status.ARCHIVED
        workspace.save(update_fields=["status", "updated_at"])
        self.assertIsNone(workspace_role_for_user(self.admin, workspace))
