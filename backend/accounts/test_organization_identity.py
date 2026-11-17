"""Organization giữ ownership; employee context và My Drive riêng không mở sang Personal."""
from datetime import timedelta
import hashlib
from io import StringIO
import secrets

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.access import (ActiveTenantRequired, can_access_workspace, get_default_tenant,
                             resolve_request_workspace)
from accounts.models import Membership, OrganizationIdentity, QuotaAccount, Tenant, Workspace, WorkspaceInvite, WorkspaceMembership
from accounts.services import get_personal_tenant, provision_organization_drive
from files.models import File, UploadSession
from files.quota import QuotaExceeded, finalize_upload_quota, reserve_upload_quota
from files.permanent_delete import permanently_delete_files
from folders.models import Folder
from sharing.models import Share
from sharing.services import can_view_file


class OrganizationIdentityTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="provisioner", is_staff=True, is_superuser=True)
        self.tenant = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name="Organization A")
        self.admin, self.admin_identity, self.admin_membership, self.admin_drive = self.managed("org-admin", role=Membership.Role.OWNER)
        self.employee, self.identity, self.membership, self.drive = self.managed("employee")

    def managed(self, name, *, role=Membership.Role.MEMBER, active=True, provision=True):
        user = get_user_model()(username=name, email=f"{name}@example.invalid", is_active=active)
        user._skip_personal_tenant_provisioning = True
        user.set_password(secrets.token_urlsafe(24)) if active else user.set_unusable_password()
        user.save()
        identity = OrganizationIdentity.objects.create(
            user=user, tenant=self.tenant, invited_by=self.actor,
            activated_at=timezone.now() if active else None,
        )
        membership = Membership.objects.create(
            user=user, tenant=self.tenant, role=role,
            status=Membership.Status.ACTIVE if active else Membership.Status.INVITED,
        )
        return user, identity, membership, provision_organization_drive(identity) if provision else None

    def request(self, user, **kwargs):
        request = RequestFactory().get("/drive/", **kwargs)
        request.user = user
        return request

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def file(self):
        return File.objects.create(tenant=self.tenant, owner=self.employee, file_name="employee.txt", file_size=3)

    def test_managed_provision_is_private_idempotent_without_personal_or_general_or_starter_quota(self):
        self.assertEqual(provision_organization_drive(self.identity).pk, self.drive.pk)
        self.assertEqual(self.drive.tenant_id, self.tenant.pk)
        self.assertFalse(self.drive.is_default)
        self.assertTrue(self.drive.is_my_drive)
        self.assertFalse(Tenant.objects.filter(personal_owner=self.employee).exists())
        self.assertFalse(Workspace.objects.filter(tenant=self.tenant, is_default=True).exists())
        self.assertFalse(QuotaAccount.objects.filter(workspace=self.drive).exists())
        self.assertEqual(resolve_request_workspace(self.request(self.employee)), self.drive)
        self.assertEqual(get_default_tenant(self.employee), self.tenant)

    def test_invited_identity_can_receive_drive_but_cannot_resolve_active_context(self):
        pending, identity, _, drive = self.managed("pending", active=False)
        self.assertEqual(drive.owned_identity_id, identity.pk)
        self.assertIsNone(resolve_request_workspace(self.request(pending)))
        with self.assertRaises(PermissionError):
            get_personal_tenant(pending)

    def test_private_drive_denies_peer_admin_platform_and_allows_explicit_share(self):
        drive_file = self.file()
        self.assertTrue(can_view_file(drive_file, self.employee))
        self.assertFalse(can_view_file(drive_file, self.admin))
        self.assertFalse(can_access_workspace(self.admin, self.drive))
        self.assertFalse(can_access_workspace(self.actor, self.drive))
        Share.objects.create(tenant=self.tenant, owner=self.employee, receiver=self.admin,
                             file=drive_file, permission=Share.Permission.VIEWER)
        self.assertTrue(can_view_file(drive_file, self.admin))

    def test_resource_model_fallbacks_use_employee_drive_not_general(self):
        drive_file = self.file()
        folder = Folder.objects.create(tenant=self.tenant, owner=self.employee, folder_name="Private")
        upload = UploadSession.objects.create(tenant=self.tenant, initiated_by=self.employee,
                                             client_name="sample.bin", expected_size_bytes=3,
                                             expires_at=timezone.now() + timedelta(hours=1))
        self.assertEqual({drive_file.workspace_id, folder.workspace_id, upload.workspace_id}, {self.drive.pk})
        self.assertFalse(Workspace.objects.filter(tenant=self.tenant, is_default=True).exists())

    def test_revoked_or_missing_home_membership_never_falls_back_to_personal(self):
        self.membership.status = Membership.Status.REVOKED
        self.membership.save(update_fields=["status"])
        self.assertIsNone(resolve_request_workspace(self.request(self.employee)))
        with self.assertRaises(ActiveTenantRequired):
            get_default_tenant(self.employee)
        self.membership.delete()
        with self.assertRaises(PermissionError):
            get_personal_tenant(self.employee)
        self.assertIsNone(resolve_request_workspace(self.request(self.employee), self.tenant))
        self.assertTrue(OrganizationIdentity.objects.filter(pk=self.employee.pk).exists())

    def test_user_deletion_is_protected_after_membership_removed(self):
        self.membership.delete()
        with self.assertRaises(ProtectedError):
            self.employee.delete()
        self.assertTrue(OrganizationIdentity.objects.filter(pk=self.employee.pk).exists())

    def test_postgresql_blocks_membership_deletion_while_content_is_retained(self):
        drive_file = self.file()
        membership_id = self.membership.pk
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.membership.delete()
            connection.check_constraints()
        self.assertTrue(Membership.objects.filter(pk=membership_id).exists())
        self.assertTrue(File.objects.filter(pk=drive_file.pk).exists())

    def test_missing_private_drive_does_not_create_general_or_repair_during_read(self):
        self.drive.delete()
        self.assertIsNone(resolve_request_workspace(self.request(self.employee)))
        self.assertFalse(Workspace.objects.filter(tenant=self.tenant, is_default=True).exists())

    def test_conflicting_duplicate_or_foreign_selectors_fail_closed(self):
        foreign = self.admin_drive.pk
        request = self.request(self.employee, data={"workspace_id": str(self.drive.pk)}, HTTP_X_WORKSPACE_ID=str(foreign))
        self.assertIsNone(resolve_request_workspace(request))
        request = self.request(self.employee, data={"workspace_id": [str(self.drive.pk), str(foreign)]})
        self.assertIsNone(resolve_request_workspace(request))
        self.assertIsNone(resolve_request_workspace(self.request(self.employee, HTTP_X_WORKSPACE_ID=str(foreign))))

    def test_explicit_workspace_resolves_before_ambiguous_legacy_default(self):
        user = get_user_model()(username="legacy-multi")
        user._skip_personal_tenant_provisioning = True
        user.save()
        other = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name="Organization B")
        Membership.objects.create(user=user, tenant=self.tenant, role=Membership.Role.ADMIN)
        Membership.objects.create(user=user, tenant=other, role=Membership.Role.ADMIN)
        with self.assertRaises(ActiveTenantRequired):
            get_default_tenant(user)
        from accounts.access import get_default_workspace
        workspace = get_default_workspace(other)
        self.assertEqual(resolve_request_workspace(self.request(user, HTTP_X_WORKSPACE_ID=str(workspace.pk))), workspace)

    def test_personal_account_with_business_membership_keeps_own_personal_drive(self):
        user = get_user_model().objects.create_user(username="personal")
        Membership.objects.create(user=user, tenant=self.tenant, role=Membership.Role.MEMBER)
        self.assertEqual(get_default_tenant(user), user.personal_tenant)
        response = self.client_for(user).get(reverse("api-current-account"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["account"]["type"], "individual")
        self.assertEqual(response.data["myDrive"]["ownership"], "personal")

    def test_explicit_collaboration_changes_context_but_not_home_and_revocation_blocks_it(self):
        other = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name="Collaborator")
        other_member = Membership.objects.create(user=self.employee, tenant=other, role=Membership.Role.MEMBER)
        workspace = Workspace.objects.create(tenant=other, name="Project", slug="project")
        WorkspaceMembership.objects.create(workspace=workspace, membership=other_member,
                                           role=WorkspaceMembership.Role.EDITOR)
        response = self.client_for(self.employee).get(reverse("api-current-account"), HTTP_X_WORKSPACE_ID=str(workspace.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["account"]["tenant"]["id"], str(other.pk))
        self.assertEqual(response.data["myDrive"]["workspaceId"], str(self.drive.pk))
        self.membership.status = Membership.Status.REVOKED
        self.membership.save(update_fields=["status"])
        self.assertIsNone(resolve_request_workspace(self.request(self.employee, HTTP_X_WORKSPACE_ID=str(workspace.pk))))
        self.assertFalse(can_access_workspace(self.employee, workspace))

    def test_revoked_home_blocks_other_organization_quota_and_member_administration(self):
        other = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name="Other administration")
        Membership.objects.create(user=self.employee, tenant=other, role=Membership.Role.ADMIN)
        target = Membership.objects.create(user=self.admin, tenant=other, role=Membership.Role.MEMBER)
        self.membership.status = Membership.Status.REVOKED
        self.membership.save(update_fields=["status"])
        client = APIClient(enforce_csrf_checks=True)
        client.force_authenticate(self.employee)
        csrf = client.get(reverse("api-csrf")).data["csrfToken"]
        response = client.get(reverse("api-organization-quota", args=[other.pk]))
        self.assertEqual(response.status_code, 404)
        response = client.post(reverse("api-suspend-tenant-member", args=[other.pk, target.pk]), HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 404)
        target.refresh_from_db()
        self.assertEqual(target.status, Membership.Status.ACTIVE)

    def test_snapshot_and_quota_use_same_private_workspace_and_collab_lists_exclude_it(self):
        client = self.client_for(self.employee)
        response = client.get(reverse("api-current-account"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["myDrive"], {"tenantId": str(self.tenant.pk), "workspaceId": str(self.drive.pk), "ownership": "organization"})
        response = client.get(reverse("api-my-workspaces"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(str(self.drive.pk), {row["id"] for row in response.data["workspaces"]})
        response = self.client_for(self.admin).get(reverse("api-workspace-members", args=[self.tenant.pk, self.drive.pk]))
        self.assertEqual(response.status_code, 404)
        response = client.patch(reverse("api-my-workspace-detail", args=[self.drive.pk]), {"status": "archived"}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_self_service_permanent_delete_is_blocked_without_creating_personal_tenant(self):
        drive_file = self.file()
        client = self.client_for(self.employee)
        response = client.post(reverse("api-delete-my-drive-data"), {"confirmation": "DELETE MY DRIVE"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(File.objects.filter(pk=drive_file.pk).exists())
        self.assertFalse(Tenant.objects.filter(personal_owner=self.employee).exists())

    def test_owned_drive_quota_reserves_tenant_and_member_with_atomic_denial(self):
        tenant_quota = QuotaAccount.objects.create(tenant=self.tenant, scope=QuotaAccount.Scope.TENANT, limit_bytes=100)
        member_quota = QuotaAccount.objects.create(tenant=self.tenant, user=self.employee, scope=QuotaAccount.Scope.MEMBER, limit_bytes=60)
        upload = UploadSession.objects.create(tenant=self.tenant, initiated_by=self.employee, client_name="sample.bin",
                                             expected_size_bytes=70, expires_at=timezone.now() + timedelta(hours=1))
        with self.assertRaises(QuotaExceeded):
            reserve_upload_quota(upload.pk, self.employee)
        tenant_quota.refresh_from_db()
        self.assertEqual(tenant_quota.reserved_bytes, 0)
        member_quota.limit_bytes = 80
        member_quota.save(update_fields=["limit_bytes"])
        self.assertEqual(len(reserve_upload_quota(upload.pk, self.employee)), 2)
        finalize_upload_quota(upload.pk, completed=True, actual_size_bytes=64)
        tenant_quota.refresh_from_db()
        member_quota.refresh_from_db()
        self.assertEqual((tenant_quota.used_bytes, member_quota.used_bytes), (64, 64))
        self.assertFalse(QuotaAccount.objects.filter(workspace=self.drive).exists())

    def test_owned_workspace_scope_is_guarded_by_model_and_postgresql_constraint(self):
        _, identity, _, _ = self.managed("unassigned", provision=False)
        other = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name="Other")
        with self.assertRaises(ValidationError):
            Workspace.objects.create(tenant=other, name="Wrong", slug="wrong", owned_identity=identity)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Workspace.objects.bulk_create([Workspace(tenant=other, name="Wrong", slug="wrong", owned_identity=identity)])
            connection.check_constraints()

    def test_quota_reconciliation_does_not_reclassify_owned_my_drive(self):
        output = StringIO()
        call_command("reconcile_workspace_quotas", stdout=output)
        self.assertIn("Legacy workspaces without dedicated accounts: 0", output.getvalue())
        self.assertFalse(QuotaAccount.objects.filter(workspace=self.drive).exists())

    def test_legacy_owned_file_deletion_releases_tenant_and_employee_quota(self):
        drive_file = self.file()
        tenant_quota = QuotaAccount.objects.create(tenant=self.tenant, scope=QuotaAccount.Scope.TENANT,
                                                  limit_bytes=100, used_bytes=8)
        member_quota = QuotaAccount.objects.create(tenant=self.tenant, user=self.employee,
                                                  scope=QuotaAccount.Scope.MEMBER, limit_bytes=20, used_bytes=3)
        peer_quota = QuotaAccount.objects.create(tenant=self.tenant, user=self.admin,
                                                scope=QuotaAccount.Scope.MEMBER, limit_bytes=20, used_bytes=5)
        self.assertEqual(permanently_delete_files([drive_file]), 1)
        tenant_quota.refresh_from_db()
        member_quota.refresh_from_db()
        peer_quota.refresh_from_db()
        self.assertEqual((tenant_quota.used_bytes, member_quota.used_bytes, peer_quota.used_bytes), (5, 0, 5))

    def test_owned_drive_rejects_ordinary_workspace_invites_before_creation(self):
        client = self.client_for(self.employee)
        response = client.post(reverse("api-create-workspace-invite", args=[self.drive.pk]),
                               {"email": self.admin.email, "role": "editor"}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(WorkspaceInvite.objects.filter(workspace=self.drive).exists())

        token = secrets.token_urlsafe(32)
        WorkspaceInvite.objects.create(workspace=self.drive, email=self.admin.email, invited_by=self.employee,
                                       role="editor", token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                       expires_at=timezone.now() + timedelta(hours=1))
        response = self.client_for(self.admin).post(reverse("api-accept-workspace-invite"),
                                                  {"token": token}, format="json")
        self.assertEqual(response.status_code, 410)

    def test_suspend_restore_retains_identity_drive_content_and_toggles_managed_login(self):
        drive_file = self.file()
        client = APIClient(enforce_csrf_checks=True)
        client.force_authenticate(self.admin)
        # DRF forced auth không bỏ CSRF decorator của mutation.
        denied = client.post(reverse("api-suspend-tenant-member", args=[self.tenant.pk, self.membership.pk]))
        self.assertEqual(denied.status_code, 403)
        csrf = client.get(reverse("api-csrf")).data["csrfToken"]
        response = client.post(reverse("api-suspend-tenant-member", args=[self.tenant.pk, self.membership.pk]), HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.is_active)
        self.assertTrue(File.objects.filter(pk=drive_file.pk).exists())
        self.assertTrue(Workspace.objects.filter(pk=self.drive.pk).exists())
        response = client.post(reverse("api-restore-tenant-member", args=[self.tenant.pk, self.membership.pk]), HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.is_active)
