"""Sprint 3.1: workspace member administration and isolation regression tests."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.access import can_access_workspace, workspace_role_for_user
from accounts.models import Membership, Workspace, WorkspaceMembership
from accounts.services import get_personal_tenant
from logs.models import ActivityLog

User = get_user_model()


class WorkspaceMemberManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="member-manager", email="manager@example.test", password="password123!",
        )
        self.viewer = User.objects.create_user(
            username="member-viewer", email="viewer@example.test", password="password123!",
        )
        self.editor = User.objects.create_user(
            username="member-editor", email="editor@example.test", password="password123!",
        )
        self.outsider = User.objects.create_user(
            username="member-outsider", email="outsider@example.test", password="password123!",
        )
        self.tenant = get_personal_tenant(self.owner)
        self.workspace = Workspace.objects.create(
            tenant=self.tenant, name="Managed Workspace", slug="managed-workspace",
            created_by=self.owner,
        )
        self.owner_membership = Membership.objects.get(tenant=self.tenant, user=self.owner)
        self.owner_assignment = WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=self.owner_membership,
            role=WorkspaceMembership.Role.ADMIN,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        self.viewer_membership = Membership.objects.create(
            tenant=self.tenant, user=self.viewer, role=Membership.Role.MEMBER,
            status=Membership.Status.ACTIVE,
        )
        self.editor_membership = Membership.objects.create(
            tenant=self.tenant, user=self.editor, role=Membership.Role.MEMBER,
            status=Membership.Status.ACTIVE,
        )
        self.viewer_assignment = WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=self.viewer_membership,
            role=WorkspaceMembership.Role.VIEWER,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        self.editor_assignment = WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=self.editor_membership,
            role=WorkspaceMembership.Role.EDITOR,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.list_url = reverse("api-my-workspace-members", args=[self.workspace.pk])

    def detail_url(self, assignment):
        return reverse("api-my-workspace-member-detail", args=[self.workspace.pk, assignment.pk])

    def test_manager_can_list_active_members_with_stable_pagination(self):
        response = self.client.get(self.list_url, {"page": 1, "page_size": 2})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["total"], 3)
        self.assertEqual(len(response.data["members"]), 2)
        self.assertTrue(response.data["hasNext"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        response2 = self.client.get(self.list_url, {"page": 2, "page_size": 2})
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(len(response2.data["members"]), 1)
        ids = {member["assignmentId"] for member in response.data["members"] + response2.data["members"]}
        self.assertEqual(len(ids), 3)
        self.assertTrue(any(member["isSelf"] and member["isProtected"] for member in response.data["members"] + response2.data["members"]))

    def test_page_size_validation(self):
        for args in ({"page": 0}, {"page": "abc"}, {"page_size": 51}, {"page_size": 0}):
            with self.subTest(args=args):
                self.assertEqual(self.client.get(self.list_url, args).status_code, 400)

    def test_viewer_and_editor_cannot_manage_workspace_members(self):
        for user in (self.viewer, self.editor):
            with self.subTest(user=user.username):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get(self.list_url).status_code, 403)
                self.assertEqual(self.client.patch(
                    self.detail_url(self.viewer_assignment), {"role": "admin"}, format="json",
                ).status_code, 403)
                self.assertEqual(self.client.delete(self.detail_url(self.viewer_assignment)).status_code, 403)
        self.viewer_assignment.refresh_from_db()
        self.assertEqual(self.viewer_assignment.role, WorkspaceMembership.Role.VIEWER)

    def test_cross_tenant_cannot_list_or_modify(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.list_url).status_code, 404)
        self.assertEqual(self.client.patch(
            self.detail_url(self.viewer_assignment), {"role": "admin"}, format="json",
        ).status_code, 404)
        self.assertEqual(self.client.delete(self.detail_url(self.viewer_assignment)).status_code, 404)

    def test_role_change_grants_editor_then_admin_and_audits_actual_changes_only(self):
        url = self.detail_url(self.viewer_assignment)
        first = self.client.patch(url, {"role": "editor"}, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        self.assertTrue(first.data["changed"])
        self.assertEqual(workspace_role_for_user(self.viewer, self.workspace), WorkspaceMembership.Role.EDITOR)
        unchanged = self.client.patch(url, {"role": "editor"}, format="json")
        self.assertEqual(unchanged.status_code, 200)
        self.assertFalse(unchanged.data["changed"])
        promoted = self.client.patch(url, {"role": "admin"}, format="json")
        self.assertEqual(promoted.status_code, 200, promoted.data)
        self.assertEqual(workspace_role_for_user(self.viewer, self.workspace), WorkspaceMembership.Role.ADMIN)
        self.assertEqual(ActivityLog.objects.filter(
            user=self.owner, workspace=self.workspace, action=ActivityLog.Action.ADD_WORKSPACE_MEMBER,
        ).count(), 2)
        self.viewer_membership.refresh_from_db()
        self.assertEqual(self.viewer_membership.role, Membership.Role.MEMBER)

    def test_promoted_workspace_admin_can_manage_another_member(self):
        elevated = self.client.patch(
            self.detail_url(self.viewer_assignment), {"role": "admin"}, format="json",
        )
        self.assertEqual(elevated.status_code, 200, elevated.data)
        self.client.force_authenticate(self.viewer)
        changed = self.client.patch(
            self.detail_url(self.editor_assignment), {"role": "viewer"}, format="json",
        )
        self.assertEqual(changed.status_code, 200, changed.data)
        self.editor_assignment.refresh_from_db()
        self.assertEqual(self.editor_assignment.role, WorkspaceMembership.Role.VIEWER)
        self.assertEqual(self.client.delete(self.detail_url(self.viewer_assignment)).status_code, 409)

    def test_archived_workspace_and_inactive_assignments_not_manageable(self):
        self.editor_assignment.status = WorkspaceMembership.Status.REVOKED
        self.editor_assignment.save(update_fields=["status", "updated_at"])
        listing = self.client.get(self.list_url)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["total"], 2)
        self.assertEqual(self.client.patch(
            self.detail_url(self.editor_assignment), {"role": "admin"}, format="json",
        ).status_code, 404)
        self.workspace.status = Workspace.Status.ARCHIVED
        self.workspace.save(update_fields=["status", "updated_at"])
        self.assertEqual(self.client.get(self.list_url).status_code, 404)
        self.assertEqual(self.client.delete(self.detail_url(self.viewer_assignment)).status_code, 404)

    def test_revoke_prevents_workspace_access_without_revoking_tenant_membership(self):
        url = self.detail_url(self.viewer_assignment)
        removed = self.client.delete(url)
        self.assertEqual(removed.status_code, 204)
        self.viewer_assignment.refresh_from_db()
        self.assertEqual(self.viewer_assignment.status, WorkspaceMembership.Status.REVOKED)
        self.assertFalse(can_access_workspace(self.viewer, self.workspace))
        self.viewer_membership.refresh_from_db()
        self.assertEqual(self.viewer_membership.status, Membership.Status.ACTIVE)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertEqual(ActivityLog.objects.filter(
            user=self.owner, workspace=self.workspace, action=ActivityLog.Action.REMOVE_WORKSPACE_MEMBER,
        ).count(), 1)

    def test_self_role_change_and_revoke_are_blocked(self):
        url = self.detail_url(self.owner_assignment)
        self.assertEqual(self.client.patch(url, {"role": "viewer"}, format="json").status_code, 409)
        self.assertEqual(self.client.delete(url).status_code, 409)
        self.assertTrue(can_access_workspace(self.owner, self.workspace))

    def test_organization_admin_assignment_is_protected(self):
        self.editor_membership.role = Membership.Role.ADMIN
        self.editor_membership.save(update_fields=["role"])
        url = self.detail_url(self.editor_assignment)
        self.assertEqual(self.client.patch(url, {"role": "viewer"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(url).status_code, 403)
        self.editor_assignment.refresh_from_db()
        self.assertEqual(self.editor_assignment.status, WorkspaceMembership.Status.ACTIVE)

    def test_invalid_payload_and_foreign_assignment_rejected(self):
        url = self.detail_url(self.viewer_assignment)
        for payload in ({}, {"role": "owner"}, {"role": "admin", "other": 1}, {"role": None}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.patch(url, payload, format="json").status_code, 400)
        other_tenant = get_personal_tenant(self.outsider)
        foreign_workspace = Workspace.objects.create(
            tenant=other_tenant, name="Foreign", slug="foreign-member-test",
            created_by=self.outsider,
        )
        foreign_member = Membership.objects.get(tenant=other_tenant, user=self.outsider)
        foreign_assignment = WorkspaceMembership.objects.create(
            workspace=foreign_workspace, membership=foreign_member,
            role=WorkspaceMembership.Role.ADMIN, status=WorkspaceMembership.Status.ACTIVE,
        )
        self.assertEqual(self.client.delete(self.detail_url(foreign_assignment)).status_code, 404)

    def test_personal_default_my_drive_cannot_be_administered_as_shared_workspace(self):
        from accounts.access import get_default_workspace
        default_ws = get_default_workspace(self.tenant)
        url = reverse("api-my-workspace-members", args=[default_ws.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_session_csrf_required_for_role_change_and_revoke(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        role_url = self.detail_url(self.viewer_assignment)
        rejected = client.patch(role_url, '{"role":"editor"}', content_type="application/json")
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(client.delete(role_url).status_code, 403)
        csrf = client.get(reverse("api-csrf"))
        self.assertEqual(csrf.status_code, 200)
        accepted = client.patch(
            role_url, '{"role":"editor"}', content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf.json()["csrfToken"],
        )
        self.assertEqual(accepted.status_code, 200, accepted.content)
