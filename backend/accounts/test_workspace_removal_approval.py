"""Thu hồi quyền Workspace Organization cần đúng cấp phê duyệt và giữ dữ liệu."""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import hashlib
import secrets
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from accounts.models import Membership, Tenant, Workspace, WorkspaceInvite, WorkspaceMembership, WorkspaceRemovalRequest
from files.models import File
from logs.models import ActivityLog


class WorkspaceRemovalApprovalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="approval-owner", email="approval-owner@example.invalid")
        self.manager = User.objects.create_user(username="approval-manager", email="approval-manager@example.invalid")
        self.target = User.objects.create_user(username="approval-target", email="approval-target@example.invalid")
        self.outsider = User.objects.create_user(username="approval-outsider", email="approval-outsider@example.invalid")
        self.tenant = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name="Approval Organization")
        self.admin_member = Membership.objects.create(tenant=self.tenant, user=self.admin, role=Membership.Role.OWNER)
        self.manager_member = Membership.objects.create(tenant=self.tenant, user=self.manager, role=Membership.Role.MEMBER)
        self.target_member = Membership.objects.create(tenant=self.tenant, user=self.target, role=Membership.Role.MEMBER)
        self.workspace = Workspace.objects.create(tenant=self.tenant, name="Project", slug="approval-project")
        self.manager_assignment = WorkspaceMembership.objects.create(workspace=self.workspace, membership=self.manager_member, role="admin")
        self.assignment = WorkspaceMembership.objects.create(workspace=self.workspace, membership=self.target_member, role="editor")
        self.client = self.as_user(self.manager)
        self.reason = "Approved project membership review"

    def as_user(self, user, *, csrf=False):
        client = APIClient(enforce_csrf_checks=csrf)
        client.force_login(user)
        return client

    def request_url(self, assignment=None):
        return reverse("api-workspace-member-removal-request", args=[self.workspace.pk, (assignment or self.assignment).pk])

    def request_removal(self):
        response = self.client.post(self.request_url(), {"reason": self.reason}, format="json")
        self.assertEqual(response.status_code, 201)
        return WorkspaceRemovalRequest.objects.get(pk=response.data["request"]["id"])

    def decide(self, row, decision="approve", *, user=None, tenant=None):
        return self.as_user(user or self.admin).post(
            reverse("api-workspace-member-removal-decision", args=[(tenant or self.tenant).pk, row.pk]),
            {"decision": decision, "reason": "Reviewed current organization membership"}, format="json")

    def test_manager_can_add_member_but_both_enterprise_delete_paths_require_approval(self):
        created = self.client.post(reverse("api-workspace-members", args=[self.tenant.pk, self.workspace.pk]),
                                   {"membership_id": str(self.target_member.pk), "role": "viewer"}, format="json")
        self.assertEqual(created.status_code, 200)
        for url in (reverse("api-my-workspace-member-detail", args=[self.workspace.pk, self.assignment.pk]),
                    reverse("api-workspace-member-detail", args=[self.tenant.pk, self.workspace.pk, self.target_member.pk])):
            response = self.client.delete(url)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.data["code"], "removal_approval_required")
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "active")

    def test_pending_request_replays_without_duplicate_and_capabilities_are_explicit(self):
        row = self.request_removal()
        duplicate = self.client.post(self.request_url(), {"reason": self.reason}, format="json")
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(WorkspaceRemovalRequest.objects.count(), 1)
        self.assertEqual(ActivityLog.objects.filter(action=ActivityLog.Action.REQUEST_WORKSPACE_REMOVAL).count(), 1)
        conflict = self.client.post(self.request_url(), {"reason": "Different removal justification"}, format="json")
        self.assertEqual(conflict.status_code, 409)
        response = self.client.get(reverse("api-my-workspace-members", args=[self.workspace.pk]))
        self.assertEqual(response.data["capabilities"], {"removeMembers": False, "requestMemberRemoval": True})
        target = next(member for member in response.data["members"] if member["assignmentId"] == str(self.assignment.pk))
        self.assertEqual(target["pendingRemovalRequestId"], str(row.pk))

    def test_org_admin_approves_once_without_deleting_account_content_or_tenant_membership(self):
        drive_file = File.objects.create(tenant=self.tenant, workspace=self.workspace, owner=self.target, file_name="retained.txt", file_size=3)
        row = self.request_removal()
        response = self.decide(row)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["request"]["status"], "approved")
        self.assignment.refresh_from_db()
        self.target_member.refresh_from_db()
        self.assertEqual(self.assignment.status, "revoked")
        self.assertEqual(self.target_member.status, "active")
        self.assertTrue(File.objects.filter(pk=drive_file.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.target.pk).exists())
        for action in (ActivityLog.Action.REQUEST_WORKSPACE_REMOVAL, ActivityLog.Action.APPROVE_WORKSPACE_REMOVAL, ActivityLog.Action.REMOVE_WORKSPACE_MEMBER):
            self.assertEqual(ActivityLog.objects.filter(action=action, workspace=self.workspace).count(), 1)
        self.assertEqual(self.decide(row).status_code, 409)
        self.assertEqual(ActivityLog.objects.filter(action=ActivityLog.Action.REMOVE_WORKSPACE_MEMBER).count(), 1)

    def test_org_admin_rejects_without_revocation_and_new_request_can_be_submitted(self):
        row = self.request_removal()
        self.assertEqual(self.decide(row, "reject").status_code, 200)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "active")
        self.assertEqual(ActivityLog.objects.filter(action=ActivityLog.Action.REJECT_WORKSPACE_REMOVAL).count(), 1)
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.Action.REMOVE_WORKSPACE_MEMBER).exists())
        self.assertNotEqual(self.request_removal().pk, row.pk)

    def test_cross_tenant_approval_and_non_admin_decision_are_denied(self):
        row = self.request_removal()
        other = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name="Other Approval Organization")
        Membership.objects.create(tenant=other, user=self.outsider, role=Membership.Role.OWNER)
        self.assertEqual(self.decide(row, user=self.outsider, tenant=other).status_code, 404)
        self.assertEqual(self.decide(row, user=self.outsider).status_code, 404)
        self.assertEqual(self.decide(row, user=self.manager).status_code, 404)
        self.assertEqual(self.as_user(self.outsider).get(reverse("api-organization-workspace-removal-requests", args=[self.tenant.pk])).status_code, 404)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "active")

    def test_actor_role_and_requester_authority_are_rechecked(self):
        row = self.request_removal()
        self.admin_member.role = Membership.Role.MEMBER
        self.admin_member.save(update_fields=["role", "updated_at"])
        self.assertEqual(self.decide(row).status_code, 404)
        self.admin_member.role = Membership.Role.OWNER
        self.admin_member.save(update_fields=["role", "updated_at"])
        self.manager_assignment.role = WorkspaceMembership.Role.VIEWER
        self.manager_assignment.save(update_fields=["role", "updated_at"])
        self.assertEqual(self.decide(row).status_code, 409)
        self.assertEqual(self.decide(row, "reject").status_code, 200)

    def test_newly_promoted_org_admin_cannot_approve_own_request(self):
        row = self.request_removal()
        self.manager_member.role = Membership.Role.ADMIN
        self.manager_member.save(update_fields=["role", "updated_at"])
        self.assertEqual(self.decide(row, user=self.manager).status_code, 403)
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")

    def test_inactive_requester_cannot_have_request_approved_but_admin_can_reject(self):
        row = self.request_removal()
        get_user_model().objects.filter(pk=self.manager.pk).update(is_active=False)
        self.assertEqual(self.decide(row).status_code, 409)
        row.refresh_from_db()
        self.assignment.refresh_from_db()
        self.assertEqual(row.status, "pending")
        self.assertEqual(self.assignment.status, "active")
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.Action.REMOVE_WORKSPACE_MEMBER).exists())
        self.assertEqual(self.decide(row, "reject").status_code, 200)

    def test_stale_revoke_and_regrant_cannot_be_removed_by_old_request(self):
        row = self.request_removal()
        self.assignment.status = WorkspaceMembership.Status.REVOKED
        self.assignment.save(update_fields=["status", "updated_at"])
        self.assertEqual(self.decide(row).status_code, 409)
        self.assignment.status = WorkspaceMembership.Status.ACTIVE
        self.assignment.save(update_fields=["status", "updated_at"])
        self.assertEqual(self.decide(row).status_code, 409)
        self.assertEqual(self.decide(row, "reject").status_code, 200)
        self.assertNotEqual(self.request_removal().pk, row.pk)

    def test_membership_changes_and_inactive_reviewer_block_approval(self):
        row = self.request_removal()
        self.target_member.status = Membership.Status.SUSPENDED
        self.target_member.save(update_fields=["status", "updated_at"])
        self.assertEqual(self.decide(row).status_code, 409)
        get_user_model().objects.filter(pk=self.admin.pk).update(is_active=False)
        response = self.decide(row)
        self.assertIn(response.status_code, (401, 403, 404))
        stale_actor = APIClient()
        stale_actor.force_authenticate(self.admin)
        denied = stale_actor.post(
            reverse("api-workspace-member-removal-decision", args=[self.tenant.pk, row.pk]),
            {"decision": "approve", "reason": self.reason}, format="json")
        self.assertEqual(denied.status_code, 404)
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")

    def test_self_and_organization_admin_targets_are_protected(self):
        self.assertEqual(self.client.post(self.request_url(self.manager_assignment), {"reason": self.reason}, format="json").status_code, 409)
        self.target_member.role = Membership.Role.ADMIN
        self.target_member.save(update_fields=["role", "updated_at"])
        self.assertEqual(self.client.post(self.request_url(), {"reason": self.reason}, format="json").status_code, 403)
        response = self.as_user(self.admin).delete(reverse("api-workspace-member-detail", args=[self.tenant.pk, self.workspace.pk, self.admin_member.pk]))
        self.assertEqual(response.status_code, 404)

    def test_personal_saas_direct_removal_and_last_manager_guard_remain(self):
        personal = self.admin.personal_tenant
        owner = Membership.objects.get(tenant=personal, user=self.admin)
        workspace = Workspace.objects.create(tenant=personal, name="SaaS", slug="saas-approval")
        owner_assignment = WorkspaceMembership.objects.create(workspace=workspace, membership=owner, role="admin")
        member = Membership.objects.create(tenant=personal, user=self.target, role=Membership.Role.MEMBER)
        target = WorkspaceMembership.objects.create(workspace=workspace, membership=member, role="viewer")
        client = self.as_user(self.admin)
        self.assertEqual(client.delete(reverse("api-my-workspace-member-detail", args=[workspace.pk, owner_assignment.pk])).status_code, 409)
        self.assertEqual(client.delete(reverse("api-my-workspace-member-detail", args=[workspace.pk, target.pk])).status_code, 204)
        self.assertEqual(client.post(reverse("api-workspace-member-removal-request", args=[workspace.pk, owner_assignment.pk]), {"reason": self.reason}, format="json").status_code, 403)

    def test_csrf_and_strict_payload_required_without_pending_writes(self):
        client = self.as_user(self.manager, csrf=True)
        self.assertEqual(client.post(self.request_url(), {"reason": self.reason}, format="json").status_code, 403)
        for body in ({"reason": "short"}, {"reason": self.reason, "tenant": str(self.tenant.pk)}, []):
            self.assertEqual(self.client.post(self.request_url(), body, format="json").status_code, 400)
        self.assertFalse(WorkspaceRemovalRequest.objects.exists())
        row = self.request_removal()
        reviewer = self.as_user(self.admin, csrf=True)
        url = reverse("api-workspace-member-removal-decision", args=[self.tenant.pk, row.pk])
        self.assertEqual(reviewer.post(url, {"decision": "approve", "reason": self.reason}, format="json").status_code, 403)
        csrf = reviewer.get(reverse("api-csrf")).data["csrfToken"]
        for body in ({"decision": "invalid", "reason": self.reason},
                     {"decision": "approve", "reason": self.reason, "workspace": str(self.workspace.pk)}):
            self.assertEqual(reviewer.post(url, body, format="json", HTTP_X_CSRFTOKEN=csrf).status_code, 400)
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")

    def test_request_scope_and_pending_uniqueness_are_database_enforced(self):
        row = self.request_removal()
        other = Workspace.objects.create(tenant=self.tenant, name="Other project", slug="other-approval")
        fields = dict(assignment=self.assignment, requested_by=self.manager, reason=self.reason,
                      expected_assignment_updated_at=self.assignment.updated_at,
                      expected_membership_updated_at=self.target_member.updated_at)
        with self.assertRaises(ValidationError):
            WorkspaceRemovalRequest.objects.create(workspace=other, **fields)
        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkspaceRemovalRequest.objects.bulk_create([WorkspaceRemovalRequest(workspace=other, **fields)])
            connection.check_constraints()
        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkspaceRemovalRequest.objects.create(workspace=self.workspace, **fields)
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")


class WorkspaceInvitationTransportTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="preview-owner", email="preview-owner@example.invalid")
        self.member = get_user_model().objects.create_user(username="preview-member", email="preview-member@example.invalid")
        self.workspace = Workspace.objects.create(tenant=self.owner.personal_tenant, name="Preview", slug="preview-body")
        self.token = secrets.token_urlsafe(32)
        self.invitation = WorkspaceInvite.objects.create(workspace=self.workspace, email=self.member.email, role="viewer", invited_by=self.owner,
            token_hash=hashlib.sha256(self.token.encode()).hexdigest(), expires_at=timezone.now() + timedelta(hours=1))

    def test_preview_post_keeps_auth_csrf_expiry_and_legacy_link_compatibility(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.member)
        url = reverse("api-preview-workspace-invite")
        self.assertEqual(client.post(url, {"token": self.token}, format="json").status_code, 403)
        csrf = client.get(reverse("api-csrf")).data["csrfToken"]
        response = client.post(url, {"token": self.token}, format="json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(client.get(url, {"token": self.token}).status_code, 200)
        self.assertEqual(client.post(url, {"token": self.token, "extra": 1}, format="json", HTTP_X_CSRFTOKEN=csrf).status_code, 400)
        self.invitation.expires_at = timezone.now() - timedelta(seconds=1)
        self.invitation.save(update_fields=["expires_at"])
        self.assertEqual(client.post(url, {"token": self.token}, format="json", HTTP_X_CSRFTOKEN=csrf).status_code, 410)
        self.assertIn(APIClient().post(url, {"token": self.token}, format="json").status_code, (401, 403))

    def test_invitation_response_is_not_cached_and_audit_has_no_raw_token(self):
        client = APIClient()
        client.force_login(self.owner)
        response = client.post(reverse("api-create-workspace-invite", args=[self.workspace.pk]), {"email": "another@example.invalid"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        token = response.data["inviteToken"]
        logs = ActivityLog.objects.filter(workspace=self.workspace)
        self.assertTrue(logs.exists())
        for row in logs:
            self.assertFalse(token in row.description)
            self.assertFalse(token in str(row.metadata))


class WorkspaceRemovalConcurrencyTests(TransactionTestCase):
    serialized_rollback = True

    def test_opposite_actor_requester_approvals_across_organizations_complete_once(self):
        User = get_user_model()
        first = User.objects.create_user(username="cross-review-first")
        second = User.objects.create_user(username="cross-review-second")

        def organization(label, administrator, manager):
            tenant = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name=f"Cross review {label}")
            Membership.objects.create(tenant=tenant, user=administrator, role=Membership.Role.OWNER)
            requester = Membership.objects.create(tenant=tenant, user=manager, role=Membership.Role.MEMBER)
            target = User.objects.create_user(username=f"cross-review-target-{label}")
            member = Membership.objects.create(tenant=tenant, user=target, role=Membership.Role.MEMBER)
            workspace = Workspace.objects.create(tenant=tenant, name=f"Project {label}", slug=f"project-{label}")
            WorkspaceMembership.objects.create(workspace=workspace, membership=requester, role="admin")
            assignment = WorkspaceMembership.objects.create(workspace=workspace, membership=member, role="viewer")
            row = WorkspaceRemovalRequest.objects.create(
                workspace=workspace, assignment=assignment, requested_by=manager,
                reason="Concurrent project membership review",
                expected_assignment_updated_at=assignment.updated_at,
                expected_membership_updated_at=member.updated_at,
            )
            return tenant.pk, row.pk, assignment.pk

        left = organization("a", first, second)
        right = organization("b", second, first)
        ready = Barrier(2)

        def approve(actor_id, scope):
            from accounts.workspace_api import decide_workspace_member_removal_view

            close_old_connections()
            try:
                # Giới hạn thời gian để lock-order regression không làm treo suite.
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                actor = User.objects.get(pk=actor_id)
                request = APIRequestFactory().post(
                    reverse("api-workspace-member-removal-decision", args=scope[:2]),
                    {"decision": "approve", "reason": "Reviewed current project membership"}, format="json")
                force_authenticate(request, user=actor)
                ready.wait(timeout=5)
                return decide_workspace_member_removal_view(request, tenant_id=scope[0], request_id=scope[1]).status_code
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            left_result = pool.submit(approve, first.pk, left)
            right_result = pool.submit(approve, second.pk, right)
            self.assertEqual([left_result.result(timeout=20), right_result.result(timeout=20)], [200, 200])
        self.assertEqual(WorkspaceRemovalRequest.objects.filter(status="approved").count(), 2)
        self.assertEqual(WorkspaceMembership.objects.filter(pk__in=[left[2], right[2]], status="revoked").count(), 2)
        self.assertEqual(ActivityLog.objects.filter(action=ActivityLog.Action.APPROVE_WORKSPACE_REMOVAL).count(), 2)
        self.assertEqual(ActivityLog.objects.filter(action=ActivityLog.Action.REMOVE_WORKSPACE_MEMBER).count(), 2)
