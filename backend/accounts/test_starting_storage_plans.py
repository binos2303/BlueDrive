"""Baseline plan allocation tests for new ordinary users and workspaces."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import QuotaAccount, StoragePlan, Tenant, Workspace
from accounts.services import get_personal_tenant


class StartingStoragePlansTests(TestCase):
    def test_new_regular_user_starts_on_free(self):
        User = get_user_model()
        owner = User.objects.create_user(username="free-starter-owner", password="pass123456")
        tenant = get_personal_tenant(owner)
        quota = QuotaAccount.objects.get(tenant=tenant, scope=QuotaAccount.Scope.TENANT)
        self.assertEqual(quota.plan_id, "free")
        self.assertEqual(quota.limit_bytes, 10 * 1024 * 1024)
        self.assertEqual(quota.used_bytes, 0)
        self.assertEqual(quota.reserved_bytes, 0)
        self.assertFalse(QuotaAccount.objects.filter(
            workspace__tenant=tenant, workspace__is_default=True,
            scope=QuotaAccount.Scope.WORKSPACE,
        ).exists())

    def test_new_workspace_starts_on_starter_for_personal_and_business(self):
        User = get_user_model()
        owner = User.objects.create_user(username="workspace-starter-owner", password="pass123456")
        personal = get_personal_tenant(owner)
        business = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name="Starter Organization")
        starter = StoragePlan.objects.get(code="workspace-starter")
        for tenant, slug in ((personal, "personal-project"), (business, "business-project")):
            ws = Workspace.objects.create(tenant=tenant, name=slug, slug=slug, created_by=owner)
            quota = QuotaAccount.objects.get(workspace=ws, scope=QuotaAccount.Scope.WORKSPACE)
            self.assertEqual(quota.plan_id, starter.code)
            self.assertEqual(quota.limit_bytes, starter.limit_bytes)
            self.assertEqual(quota.used_bytes, 0)

    def test_changes_to_plan_size_only_affect_future_allocations(self):
        User = get_user_model()
        first = User.objects.create_user(username="free-existing", password="pass123456")
        old_quota = QuotaAccount.objects.get(
            tenant=get_personal_tenant(first), scope=QuotaAccount.Scope.TENANT,
        )
        old_limit = old_quota.limit_bytes
        free = StoragePlan.objects.get(code="free")
        free.limit_bytes = 25 * 1024 * 1024
        free.save(update_fields=["limit_bytes"])
        second = User.objects.create_user(username="free-next", password="pass123456")
        second_quota = QuotaAccount.objects.get(
            tenant=get_personal_tenant(second), scope=QuotaAccount.Scope.TENANT,
        )
        old_quota.refresh_from_db()
        self.assertEqual(old_quota.limit_bytes, old_limit)
        self.assertEqual(old_quota.plan_id, "free")
        self.assertEqual(second_quota.plan_id, "free")
        self.assertEqual(second_quota.limit_bytes, 25 * 1024 * 1024)

    def test_workspace_plan_change_does_not_retroactively_reassign(self):
        User = get_user_model()
        owner = User.objects.create_user(username="starter-existing", password="pass123456")
        tenant = get_personal_tenant(owner)
        first = Workspace.objects.create(tenant=tenant, name="Original", slug="original", created_by=owner)
        first_quota = QuotaAccount.objects.get(workspace=first)
        original_limit = first_quota.limit_bytes
        starter = StoragePlan.objects.get(code="workspace-starter")
        starter.limit_bytes = 80 * 1024 * 1024
        starter.save(update_fields=["limit_bytes"])
        second = Workspace.objects.create(tenant=tenant, name="New", slug="new", created_by=owner)
        first_quota.refresh_from_db()
        second_quota = QuotaAccount.objects.get(workspace=second)
        self.assertEqual(first_quota.limit_bytes, original_limit)
        self.assertEqual(second_quota.limit_bytes, starter.limit_bytes)
        self.assertEqual(second_quota.plan_id, "workspace-starter")

    def test_platform_admin_does_not_receive_free_drive(self):
        User = get_user_model()
        admin = User.objects.create_superuser(
            username="no-free-for-admin", email="admin@example.test", password="pass123456"
        )
        self.assertFalse(Tenant.objects.filter(personal_owner=admin).exists())
