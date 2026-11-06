"""Tests for editable quota presets, deletion, quota thresholds and safe activity projection."""
import json
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.management import call_command
from io import StringIO
from django.urls import reverse

from accounts.models import (
    StoragePlan, StoragePlanAuditEvent, StoragePolicy, StoragePolicyAuditEvent,
    QuotaAccount, Tenant,
)
from files.models import File
from logs.models import ActivityLog
from logs.services import log_action
from folders.models import Folder


class AdminPlanPolicyTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="plan-admin", email="padmin@example.test", password="testPass123!")
        self.owner = User.objects.create_user(username="plan-owner", email="powner@example.test", password="testPass123!")
        self.tenant = self.owner.personal_tenant
        self.client.force_login(self.admin)

    def test_create_plan_and_audit(self):
        response = self.client.post(reverse("api-admin-quota-plan-create"),
            data=json.dumps({"code": "test-quota-plan", "name": "Test Plan", "scope": "personal",
                             "limit_bytes": 123456, "reason": "Create a test preset"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 201)
        plan = StoragePlan.objects.get(pk="test-quota-plan")
        self.assertEqual(plan.limit_bytes, 123456)
        self.assertTrue(StoragePlanAuditEvent.objects.filter(plan_code=plan.code, action="created").exists())
        self.assertEqual(self.client.post(reverse("api-admin-quota-plan-create"),
            data=json.dumps({"code": "test-quota-plan", "name": "Test Plan", "scope": "personal",
                             "limit_bytes": 123456, "reason": "Duplicate plan attempt"}),
            content_type="application/json").status_code, 409)

    def test_update_plan_preserves_existing_assignments(self):
        plan = StoragePlan.objects.get(code="development")
        quota = QuotaAccount.objects.get(tenant=self.tenant, scope=QuotaAccount.Scope.TENANT)
        quota.plan = plan
        quota.limit_bytes = 1234
        quota.save(update_fields=["plan", "limit_bytes"])
        response = self.client.patch(reverse("api-admin-quota-plan-update", kwargs={"code": plan.code}),
            data=json.dumps({"name": "Dev plan renamed", "limit_bytes": 9999,
                             "is_active": False, "reason": "Change future quota presets"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        quota.refresh_from_db()
        self.assertEqual(quota.limit_bytes, 1234)
        self.assertEqual(quota.plan_id, plan.code)
        self.assertTrue(StoragePlanAuditEvent.objects.filter(plan_code=plan.code, action="updated").exists())

    def test_policy_thresholds_only_and_share_size_payload_rejected(self):
        url = reverse("api-admin-quota-policy-update")
        bad = self.client.patch(url, data=json.dumps({"warning_percent": 95, "critical_percent": 80,
            "reason": "Invalid thresholds attempt"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        removed_option = self.client.patch(url, data=json.dumps({"max_personal_file_bytes": 20,
            "warning_percent": 70, "critical_percent": 90,
            "reason": "Removed share-size option"}), content_type="application/json")
        self.assertEqual(removed_option.status_code, 400)
        result = self.client.patch(url, data=json.dumps({"warning_percent": 70,
            "critical_percent": 90, "reason": "Update quota warning levels"}), content_type="application/json")
        self.assertEqual(result.status_code, 200)
        policy = StoragePolicy.objects.get(pk=1)
        self.assertEqual(policy.warning_percent, 70)
        self.assertEqual(policy.critical_percent, 90)
        self.assertEqual(StoragePolicyAuditEvent.objects.count(), 1)

    def test_regular_user_cannot_edit_presets_or_policy(self):
        self.client.force_login(self.owner)
        payload = {"code": "bad-plan", "name": "Bad plan", "scope": "personal", "limit_bytes": 100,
                   "reason": "User must not be admin"}
        self.assertEqual(self.client.post(reverse("api-admin-quota-plan-create"),
            data=json.dumps(payload), content_type="application/json").status_code, 403)
        self.assertEqual(self.client.patch(reverse("api-admin-quota-policy-update"),
            data=json.dumps({"warning_percent": 80, "critical_percent": 95,
                "reason": "Unauthorized user update"}),
            content_type="application/json").status_code, 403)
        self.assertEqual(self.client.delete(reverse("api-admin-quota-plan-delete", kwargs={"code": "pro"}),
            data=json.dumps({"reason": "Unauthorized delete attempt"}),
            content_type="application/json").status_code, 403)

    def test_delete_unassigned_plan_is_audited(self):
        code = "pro"
        self.assertFalse(QuotaAccount.objects.filter(plan_id=code).exists())
        result = self.client.delete(reverse("api-admin-quota-plan-delete", kwargs={"code": code}),
            data=json.dumps({"reason": "Remove unused preset safely"}), content_type="application/json")
        self.assertEqual(result.status_code, 204)
        self.assertFalse(StoragePlan.objects.filter(pk=code).exists())
        self.assertTrue(StoragePlanAuditEvent.objects.filter(plan_code=code, action="deleted").exists())

    def test_delete_assigned_plan_is_blocked_without_quota_changes(self):
        plan = StoragePlan.objects.get(pk="development")
        quota = QuotaAccount.objects.get(tenant=self.tenant, scope=QuotaAccount.Scope.TENANT)
        quota.plan = plan
        quota.limit_bytes = 56789
        quota.save(update_fields=["plan", "limit_bytes"])
        result = self.client.delete(reverse("api-admin-quota-plan-delete", kwargs={"code": plan.code}),
            data=json.dumps({"reason": "Remove obsolete but assigned plan"}), content_type="application/json")
        self.assertEqual(result.status_code, 409)
        quota.refresh_from_db()
        self.assertEqual(quota.plan_id, plan.code)
        self.assertEqual(quota.limit_bytes, 56789)
        self.assertTrue(StoragePlan.objects.filter(pk=plan.code).exists())

    def test_baseline_plans_cannot_be_deleted(self):
        for code in ("free", "workspace-starter"):
            response = self.client.delete(reverse("api-admin-quota-plan-delete", kwargs={"code": code}),
                data=json.dumps({"reason": "Preserve baseline allocation plans"}), content_type="application/json")
            self.assertEqual(response.status_code, 409)

    def test_prune_plans_preserves_assigned_quota_and_baselines(self):
        plan = StoragePlan.objects.get(pk="development")
        quota = QuotaAccount.objects.get(tenant=self.tenant, scope=QuotaAccount.Scope.TENANT)
        quota.plan = plan
        quota.limit_bytes = 123456
        quota.save(update_fields=["plan", "limit_bytes"])
        out = StringIO()
        call_command("prune_storage_plans", stdout=out)
        self.assertIn("DRY RUN", out.getvalue())
        self.assertTrue(StoragePlan.objects.get(pk="pro").is_active)

        call_command("prune_storage_plans", apply=True, actor=self.admin.username, stdout=StringIO())
        self.assertEqual(set(StoragePlan.objects.filter(is_active=True).values_list("code", flat=True)),
                         {"free", "workspace-starter"})
        self.assertFalse(StoragePlan.objects.get(pk="development").is_active)
        self.assertFalse(StoragePlan.objects.filter(pk="pro").exists())
        quota.refresh_from_db()
        self.assertEqual(quota.plan_id, "development")
        self.assertEqual(quota.limit_bytes, 123456)
        self.assertTrue(StoragePlanAuditEvent.objects.filter(plan_code="pro", action="deleted").exists())

    def test_share_size_setting_is_no_longer_enforced(self):
        from sharing.policy import file_share_allowed, folder_share_allowed
        default_space = self.tenant.workspaces.get(is_default=True)
        file = File.objects.create(tenant=self.tenant, owner=self.owner,
            workspace=default_space, file_name="large.bin", file_size=300)
        folder = Folder.objects.create(tenant=self.tenant, owner=self.owner,
            workspace=default_space, folder_name="Uploads")
        policy, _ = StoragePolicy.objects.get_or_create(pk=1)
        policy.max_personal_file_bytes = 1  # Legacy value is ignored.
        policy.save(update_fields=["max_personal_file_bytes"])
        self.assertTrue(file_share_allowed(file))
        self.assertTrue(folder_share_allowed(folder))
        payload = self.client.get(reverse("api-admin-quota-policy")).json()
        self.assertNotIn("max_personal_file_bytes", payload)

    def test_activity_share_metadata_is_projected_safely(self):
        log_action(self.owner, ActivityLog.Action.SHARE, "Shared report", metadata={
            "recipient_email": "recipient@example.test", "recipient_username": "recipient",
            "permission": "viewer", "shared_count": 1, "resource_names": ["report.pdf"],
            "private_token": "DO_NOT_EXPOSE"})
        response = self.client.get(reverse("api-admin-activity"), {"action": "SHARE"})
        self.assertEqual(response.status_code, 200)
        event = response.json()["results"][0]
        self.assertEqual(event["share"]["recipient"], "recipient@example.test")
        self.assertEqual(event["share"]["permission"], "viewer")
        self.assertNotIn("private_token", str(event))
        self.assertNotIn("description", event)
