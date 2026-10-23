"""Regression tests for personal SaaS workspaces and email-bound invitations."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.access import get_default_workspace
from accounts.models import Membership, Workspace, WorkspaceMembership
from accounts.services import get_personal_tenant
from logs.models import ActivityLog


User = get_user_model()


class PersonalSaaSWorkspaceApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="saas-owner",
            email="saas-owner@example.test",
            password="test-password",
        )
        self.member = User.objects.create_user(
            username="saas-invitee",
            email="saas-invitee@example.test",
            password="test-password",
        )
        self.owner_tenant = get_personal_tenant(self.owner)
        self.default_workspace = get_default_workspace(self.owner_tenant)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_create_workspace_keeps_my_drive_separate_and_appears_in_listing(self):
        initial = self.client.get(reverse("api-my-workspaces"))
        self.assertEqual(initial.status_code, 200)
        self.assertNotIn(str(self.default_workspace.pk), {row["id"] for row in initial.data["workspaces"]})

        response = self.client.post(
            reverse("api-my-workspaces"),
            {
                "name": "Design Studio",
                "description": "Product design collaboration",
                "default_member_role": WorkspaceMembership.Role.VIEWER,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        workspace = Workspace.objects.get(pk=response.data["workspace"]["id"])
        self.assertEqual(workspace.tenant_id, self.owner_tenant.pk)
        self.assertFalse(workspace.is_default)
        self.assertTrue(WorkspaceMembership.objects.filter(
            workspace=workspace,
            membership__user=self.owner,
            role=WorkspaceMembership.Role.ADMIN,
            status=WorkspaceMembership.Status.ACTIVE,
        ).exists())
        listed = self.client.get(reverse("api-my-workspaces"))
        self.assertIn(str(workspace.pk), {row["id"] for row in listed.data["workspaces"]})

    def test_invite_is_email_bound_single_use_and_grants_only_selected_workspace(self):
        workspace = Workspace.objects.create(
            tenant=self.owner_tenant,
            name="Invite Only",
            slug="invite-only",
            created_by=self.owner,
        )
        owner_membership = Membership.objects.get(tenant=self.owner_tenant, user=self.owner)
        WorkspaceMembership.objects.update_or_create(
            workspace=workspace,
            membership=owner_membership,
            defaults={
                "role": WorkspaceMembership.Role.ADMIN,
                "status": WorkspaceMembership.Status.ACTIVE,
                "created_by": self.owner,
            },
        )
        invite_response = self.client.post(
            reverse("api-create-workspace-invite", args=[workspace.pk]),
            {"email": self.member.email, "role": WorkspaceMembership.Role.EDITOR},
            format="json",
        )
        self.assertEqual(invite_response.status_code, 201, invite_response.data)
        token = invite_response.data["inviteToken"]

        member_client = APIClient()
        member_client.force_authenticate(self.member)
        preview = member_client.get(reverse("api-preview-workspace-invite"), {"token": token})
        self.assertEqual(preview.status_code, 200, preview.data)

        accept = member_client.post(
            reverse("api-accept-workspace-invite"),
            {"token": token},
            format="json",
        )
        self.assertEqual(accept.status_code, 200, accept.data)
        assignment = WorkspaceMembership.objects.get(
            workspace=workspace,
            membership__user=self.member,
        )
        self.assertEqual(assignment.role, WorkspaceMembership.Role.EDITOR)

        default_workspace = get_default_workspace(self.owner_tenant)
        self.assertFalse(WorkspaceMembership.objects.filter(
            workspace=default_workspace,
            membership__user=self.member,
            status=WorkspaceMembership.Status.ACTIVE,
        ).exists())
        replay = member_client.post(
            reverse("api-accept-workspace-invite"),
            {"token": token},
            format="json",
        )
        self.assertEqual(replay.status_code, 410)
        self.assertTrue(ActivityLog.objects.filter(
            workspace=workspace,
            user=self.member,
            action=ActivityLog.Action.JOIN_WORKSPACE,
        ).exists())

        # Workspace timeline is manager-only: the owner can see the join event,
        # but an Editor cannot inspect the activity of every other member.
        owner_timeline = self.client.get(reverse("api-workspace-activity", args=[workspace.pk]))
        self.assertEqual(owner_timeline.status_code, 200, owner_timeline.data)
        self.assertIn(ActivityLog.Action.JOIN_WORKSPACE, {row["action"] for row in owner_timeline.data["events"]})
        member_timeline = member_client.get(reverse("api-workspace-activity", args=[workspace.pk]))
        self.assertEqual(member_timeline.status_code, 403)

    def test_invitation_cannot_be_accepted_by_a_different_email(self):
        workspace = Workspace.objects.create(
            tenant=self.owner_tenant,
            name="Email Restricted",
            slug="email-restricted",
            created_by=self.owner,
        )
        invite = self.client.post(
            reverse("api-create-workspace-invite", args=[workspace.pk]),
            {"email": self.member.email, "role": WorkspaceMembership.Role.VIEWER},
            format="json",
        )
        self.assertEqual(invite.status_code, 201, invite.data)

        other_user = User.objects.create_user(
            username="wrong-email",
            email="wrong-email@example.test",
            password="test-password",
        )
        other_client = APIClient()
        other_client.force_authenticate(other_user)
        response = other_client.post(
            reverse("api-accept-workspace-invite"),
            {"token": invite.data["inviteToken"]},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(WorkspaceMembership.objects.filter(
            workspace=workspace,
            membership__user=other_user,
        ).exists())
