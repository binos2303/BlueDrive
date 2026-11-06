"""Quota scope isolation and least-privilege administrative assignment tests."""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import QuotaAccount, QuotaAuditEvent, StoragePlan, Workspace
from files.models import File, UploadSession
from files.quota import QuotaExceeded, QuotaStateError, reserve_upload_quota, finalize_upload_quota
from files.permanent_delete import permanently_delete_files


class QuotaManagementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superadmin = User.objects.create_superuser(username="quota-superadmin", email="sup@example.test", password="pass123456")
        self.owner = User.objects.create_user(username="quota-owner", email="owner@example.test", password="pass123456")
        self.tenant = self.owner.personal_tenant
        self.my_drive = Workspace.objects.get(tenant=self.tenant, is_default=True)
        self.space = Workspace.objects.create(tenant=self.tenant, slug="project", name="Project", created_by=self.owner)
        self.personal_quota = QuotaAccount.objects.get(tenant=self.tenant, scope="tenant")
        self.workspace_quota = QuotaAccount.objects.get(workspace=self.space, scope="workspace")
        self.personal_quota.limit_bytes = 100
        self.personal_quota.save(update_fields=["limit_bytes"])
        self.workspace_quota.limit_bytes = 60
        self.workspace_quota.save(update_fields=["limit_bytes"])

    def make_upload(self, workspace, size):
        return UploadSession.objects.create(
            tenant=self.tenant, workspace=workspace, initiated_by=self.owner,
            client_name="sample.bin", expected_size_bytes=size,
            expires_at=timezone.now() + timedelta(hours=1),
        )

    def test_independent_workspace_quota_and_private_drive(self):
        default_upload = self.make_upload(self.my_drive, 70)
        reserve_upload_quota(default_upload.pk, self.owner)
        workspace_upload = self.make_upload(self.space, 50)
        reserve_upload_quota(workspace_upload.pk, self.owner)
        self.personal_quota.refresh_from_db()
        self.workspace_quota.refresh_from_db()
        self.assertEqual(self.personal_quota.reserved_bytes, 70)
        self.assertEqual(self.workspace_quota.reserved_bytes, 50)
        with self.assertRaises(QuotaExceeded):
            reserve_upload_quota(self.make_upload(self.space, 11).pk, self.owner)
        finalize_upload_quota(workspace_upload.pk, completed=True, actual_size_bytes=40, actor=self.owner)
        self.personal_quota.refresh_from_db()
        self.workspace_quota.refresh_from_db()
        self.assertEqual(self.personal_quota.used_bytes, 0)
        self.assertEqual(self.workspace_quota.used_bytes, 40)
        self.assertEqual(self.workspace_quota.reserved_bytes, 0)

    def test_missing_workspace_quota_fails_closed(self):
        self.workspace_quota.delete()
        with self.assertRaises(QuotaStateError):
            reserve_upload_quota(self.make_upload(self.space, 20).pk, self.owner)

    def test_quota_directory_and_plans(self):
        self.client.force_login(self.superadmin)
        response = self.client.get(reverse("api-admin-quotas"), {"scope": "workspace"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(str(self.space.pk), [r["id"] for r in response.json()["results"]])
        response = self.client.get(reverse("api-admin-quotas"), {"scope": "personal"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(r["quota"] and r["quota"]["id"] == str(self.personal_quota.pk) for r in response.json()["results"]))
        plans = self.client.get(reverse("api-admin-quota-plans"))
        self.assertEqual(plans.status_code, 200)
        self.assertTrue(any(p["code"] == "development" for p in plans.json()["plans"]))

    def test_superadmin_can_assign_plan_and_creates_audit_event(self):
        self.client.force_login(self.superadmin)
        result = self.client.patch(
            reverse("api-admin-quota-update", kwargs={"quota_id": self.personal_quota.pk}),
            data=json.dumps({"reason": "Upgrade allocated by administrator", "plan_code": "free", "limit_bytes": None}),
            content_type="application/json",
        )
        self.assertEqual(result.status_code, 200)
        self.personal_quota.refresh_from_db()
        self.assertEqual(self.personal_quota.plan_id, "free")
        self.assertEqual(self.personal_quota.limit_bytes, StoragePlan.objects.get(code="free").limit_bytes)
        event = QuotaAuditEvent.objects.get(quota_account=self.personal_quota)
        self.assertEqual(event.actor, self.superadmin)

    def test_regular_user_cannot_read_or_update_platform_quota(self):
        self.client.force_login(self.owner)
        result = self.client.get(reverse("api-admin-quotas"))
        self.assertEqual(result.status_code, 403)
        result = self.client.patch(
            reverse("api-admin-quota-update", kwargs={"quota_id": self.personal_quota.pk}),
            data=json.dumps({"reason": "Attempt to change another user", "plan_code": None, "limit_bytes": 500}),
            content_type="application/json",
        )
        self.assertEqual(result.status_code, 403)

    def test_invalid_plan_scope_does_not_change_limit(self):
        self.client.force_login(self.superadmin)
        result = self.client.patch(
            reverse("api-admin-quota-update", kwargs={"quota_id": self.workspace_quota.pk}),
            data=json.dumps({"reason": "Trying incorrect package category", "plan_code": "free", "limit_bytes": None}),
            content_type="application/json",
        )
        self.assertEqual(result.status_code, 400)
        self.workspace_quota.refresh_from_db()
        self.assertEqual(self.workspace_quota.limit_bytes, 60)

    def test_legacy_file_without_reservation_releases_scope_usage_on_delete(self):
        file = File.objects.create(
            tenant=self.tenant, workspace=self.space, owner=self.owner,
            file_name="legacy.txt", file_size=7,
        )
        self.workspace_quota.used_bytes = 7
        self.workspace_quota.save(update_fields=["used_bytes"])
        permanently_delete_files([file])
        self.workspace_quota.refresh_from_db()
        self.assertEqual(self.workspace_quota.used_bytes, 0)
        self.assertEqual(self.personal_quota.used_bytes, 0)


class OrganizationQuotaAuthorizationTests(TestCase):
    def setUp(self):
        from accounts.models import Tenant, Membership
        User = get_user_model()
        self.owner = User.objects.create_user(username="org-owner", password="pass123456")
        self.stranger = User.objects.create_user(username="org-outsider", password="pass123456")
        self.employee = User.objects.create_user(username="org-employee", password="pass123456")
        self.organization = Tenant.objects.create(name="Quota Enterprise", kind=Tenant.Kind.BUSINESS)
        Membership.objects.create(tenant=self.organization, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(tenant=self.organization, user=self.employee, role=Membership.Role.MEMBER)
        self.workspace = Workspace.objects.create(tenant=self.organization, name="Engineering", slug="engineering")
        self.quota = QuotaAccount.objects.get(workspace=self.workspace, scope=QuotaAccount.Scope.WORKSPACE)
        self.url = reverse("api-organization-quota", kwargs={"tenant_id": self.organization.pk})

    def test_organization_owner_may_allocate_own_workspace(self):
        self.client.force_login(self.owner)
        response = self.client.patch(self.url, data=json.dumps({
            "scope": "workspace", "target_id": str(self.workspace.pk),
            "limit_bytes": 200 * 1024 * 1024,
            "reason": "Allocating engineering storage",
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.quota.refresh_from_db()
        self.assertEqual(self.quota.limit_bytes, 200 * 1024 * 1024)
        self.assertTrue(QuotaAuditEvent.objects.filter(actor=self.owner, quota_account=self.quota).exists())

    def test_non_admin_and_outsider_cannot_edit_quota(self):
        for user in [self.employee, self.stranger]:
            self.client.force_login(user)
            response = self.client.patch(self.url, data=json.dumps({
                "scope": "workspace", "target_id": str(self.workspace.pk),
                "limit_bytes": 900 * 1024 * 1024,
                "reason": "Attempting quota escalation",
            }), content_type="application/json")
            self.assertEqual(response.status_code, 404)
        self.quota.refresh_from_db()
        self.assertEqual(self.quota.limit_bytes, 100 * 1024 * 1024)
