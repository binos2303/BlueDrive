from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.access import workspace_role_for_user
from accounts.models import (
    Group,
    GroupMembership,
    Membership,
    Tenant,
    Workspace,
    WorkspaceGroupAccess,
    WorkspaceMembership,
)
from logs.models import ActivityLog


User = get_user_model()


class WorkspaceAndGroupApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="org-admin",
            email="org-admin@example.test",
            password="test-password",
        )
        self.tenant = Tenant.objects.create(
            kind=Tenant.Kind.BUSINESS,
            name="Example Corporation",
        )
        self.admin_membership = Membership.objects.create(
            tenant=self.tenant,
            user=self.admin,
            role=Membership.Role.ADMIN,
            status=Membership.Status.ACTIVE,
        )
        self.member = User.objects.create_user(
            username="org-member",
            email="org-member@example.test",
            password="test-password",
        )
        self.member_membership = Membership.objects.create(
            tenant=self.tenant,
            user=self.member,
            role=Membership.Role.MEMBER,
            status=Membership.Status.ACTIVE,
        )
        self.client.force_authenticate(self.admin)

    def test_admin_can_create_workspace_and_creator_is_workspace_admin(self):
        response = self.client.post(
            reverse("api-organization-workspaces", args=[self.tenant.pk]),
            {"name": "Engineering", "description": "Engineering documents"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        workspace = Workspace.objects.get(pk=response.data["workspace"]["id"])
        assignment = WorkspaceMembership.objects.get(
            workspace=workspace,
            membership=self.admin_membership,
        )
        self.assertEqual(assignment.role, WorkspaceMembership.Role.ADMIN)
        self.assertTrue(
            ActivityLog.objects.filter(
                tenant=self.tenant,
                user=self.admin,
                action=ActivityLog.Action.CREATE_WORKSPACE,
                metadata__workspace_id=str(workspace.pk),
            ).exists()
        )

    def test_non_admin_cannot_create_workspace_or_manage_groups(self):
        self.client.force_authenticate(self.member)

        response = self.client.post(
            reverse("api-organization-workspaces", args=[self.tenant.pk]),
            {"name": "Unauthorized"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            reverse("api-organization-groups", args=[self.tenant.pk]),
            {"name": "Unauthorized Group"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_group_grant_resolves_workspace_role(self):
        workspace = Workspace.objects.create(
            tenant=self.tenant,
            name="Engineering",
            slug="engineering",
        )
        group = Group.objects.create(
            tenant=self.tenant,
            name="Developers",
            created_by=self.admin,
        )
        GroupMembership.objects.create(
            group=group,
            membership=self.member_membership,
            added_by=self.admin,
        )

        response = self.client.post(
            reverse(
                "api-workspace-groups",
                args=[self.tenant.pk, workspace.pk],
            ),
            {"group_id": str(group.pk), "role": WorkspaceGroupAccess.Role.EDITOR},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            workspace_role_for_user(self.member, workspace),
            WorkspaceMembership.Role.EDITOR,
        )

    def test_group_cannot_be_granted_to_workspace_in_another_tenant(self):
        other_tenant = Tenant.objects.create(
            kind=Tenant.Kind.BUSINESS,
            name="Other Corporation",
        )
        other_workspace = Workspace.objects.create(
            tenant=other_tenant,
            name="Other General",
            slug="other-general",
            is_default=True,
        )
        group = Group.objects.create(
            tenant=self.tenant,
            name="Restricted Group",
        )

        response = self.client.post(
            reverse(
                "api-workspace-groups",
                args=[other_tenant.pk, other_workspace.pk],
            ),
            {"group_id": str(group.pk), "role": WorkspaceGroupAccess.Role.VIEWER},
            format="json",
        )

        # The caller is not a member of the other organization; it must not
        # disclose that the supplied workspace or group exists.
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            WorkspaceGroupAccess.objects.filter(
                workspace=other_workspace,
                group=group,
            ).exists()
        )

    def test_archived_group_grant_no_longer_grants_workspace_access(self):
        workspace = Workspace.objects.create(
            tenant=self.tenant,
            name="Research",
            slug="research",
        )
        group = Group.objects.create(
            tenant=self.tenant,
            name="Researchers",
        )
        GroupMembership.objects.create(group=group, membership=self.member_membership)
        WorkspaceGroupAccess.objects.create(
            workspace=workspace,
            group=group,
            role=WorkspaceGroupAccess.Role.VIEWER,
        )
        self.assertEqual(
            workspace_role_for_user(self.member, workspace),
            WorkspaceMembership.Role.VIEWER,
        )

        group.status = Group.Status.ARCHIVED
        group.save(update_fields=["status", "updated_at"])

        self.assertIsNone(workspace_role_for_user(self.member, workspace))
