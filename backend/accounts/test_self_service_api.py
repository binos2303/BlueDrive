"""Tests for private account activity, search history and My Drive deletion."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.access import get_default_workspace
from accounts.models import Membership, QuotaAccount, Tenant, Workspace, WorkspaceMembership
from accounts.services import get_personal_tenant
from files.models import File
from folders.models import Folder
from logs.models import ActivityLog, SearchHistory


User = get_user_model()


class SelfServiceApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="privacy-user",
            email="privacy-user@example.test",
            password="Correct-password-123!",
        )
        self.other = User.objects.create_user(
            username="other-privacy-user",
            email="other-privacy-user@example.test",
            password="Correct-password-456!",
        )
        self.tenant = get_personal_tenant(self.user)
        self.workspace = get_default_workspace(self.tenant)
        self.other_tenant = get_personal_tenant(self.other)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_activity_and_search_history_are_scoped_to_the_authenticated_user(self):
        ActivityLog.objects.create(
            user=self.user,
            tenant=self.tenant,
            workspace=self.workspace,
            action=ActivityLog.Action.VIEW,
            description="My activity",
        )
        ActivityLog.objects.create(
            user=self.other,
            tenant=self.other_tenant,
            action=ActivityLog.Action.VIEW,
            description="Other user's activity",
        )
        SearchHistory.objects.create(user=self.user, tenant=self.tenant, workspace=self.workspace, query="private query")
        other_history = SearchHistory.objects.create(user=self.other, tenant=self.other_tenant, query="other query")

        activity = self.client.get(reverse("api-my-activity"))
        self.assertEqual(activity.status_code, 200)
        self.assertIn("My activity", {row["description"] for row in activity.data["events"]})
        self.assertNotIn("Other user's activity", {row["description"] for row in activity.data["events"]})

        history = self.client.get(reverse("api-my-search-history"))
        self.assertEqual(history.status_code, 200)
        self.assertEqual([row["query"] for row in history.data["items"]], ["private query"])

        cleared = self.client.delete(reverse("api-my-search-history"))
        self.assertEqual(cleared.status_code, 200)
        self.assertFalse(SearchHistory.objects.filter(user=self.user).exists())
        self.assertTrue(SearchHistory.objects.filter(pk=other_history.pk).exists())

    def test_shared_personal_workspace_does_not_disclose_owner_tenant_usage(self):
        shared_workspace = Workspace.objects.create(
            tenant=self.tenant,
            name="Guest collaboration",
            slug="guest-collaboration",
            created_by=self.user,
        )
        guest_membership = Membership.objects.create(
            tenant=self.tenant,
            user=self.other,
            role=Membership.Role.MEMBER,
            status=Membership.Status.ACTIVE,
        )
        WorkspaceMembership.objects.create(
            workspace=shared_workspace,
            membership=guest_membership,
            role=WorkspaceMembership.Role.EDITOR,
        )
        QuotaAccount.objects.filter(
            tenant=self.tenant,
            scope=QuotaAccount.Scope.TENANT,
        ).update(used_bytes=9000, limit_bytes=10000)

        self.client.force_authenticate(self.other)
        response = self.client.get(
            reverse("api-my-quota"),
            HTTP_X_WORKSPACE_ID=str(shared_workspace.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["configured"])
        self.assertIsNone(response.data["usedBytes"])
        self.assertIn("Individual usage is not currently tracked", response.data["message"])

    def test_business_quota_requires_member_allocation_before_uploads_allowed(self):
        business = Tenant.objects.create(
            kind=Tenant.Kind.BUSINESS,
            name="Quota Organization",
            status=Tenant.Status.ACTIVE,
        )
        Membership.objects.create(
            tenant=business,
            user=self.user,
            role=Membership.Role.OWNER,
            status=Membership.Status.ACTIVE,
        )
        workspace = get_default_workspace(business)
        QuotaAccount.objects.create(
            tenant=business,
            scope=QuotaAccount.Scope.TENANT,
            limit_bytes=10000,
            used_bytes=100,
            reserved_bytes=0,
        )

        response = self.client.get(
            reverse("api-my-quota"),
            HTTP_X_WORKSPACE_ID=str(workspace.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["configured"])
        self.assertIn("allocate a member quota", response.data["message"])

    def test_business_quota_reports_member_and_organization_caps(self):
        business = Tenant.objects.create(
            kind=Tenant.Kind.BUSINESS,
            name="Quota Organization With Allocation",
            status=Tenant.Status.ACTIVE,
        )
        Membership.objects.create(
            tenant=business,
            user=self.user,
            role=Membership.Role.OWNER,
            status=Membership.Status.ACTIVE,
        )
        workspace = get_default_workspace(business)
        QuotaAccount.objects.create(
            tenant=business,
            scope=QuotaAccount.Scope.TENANT,
            limit_bytes=10000,
            used_bytes=7000,
            reserved_bytes=500,
        )
        QuotaAccount.objects.create(
            tenant=business,
            scope=QuotaAccount.Scope.MEMBER,
            user=self.user,
            limit_bytes=3000,
            used_bytes=400,
            reserved_bytes=100,
        )

        response = self.client.get(
            reverse("api-my-quota"),
            HTTP_X_WORKSPACE_ID=str(workspace.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["configured"])
        self.assertEqual(response.data["scope"], QuotaAccount.Scope.MEMBER)
        self.assertEqual(response.data["usedBytes"], 400)
        self.assertEqual(response.data["organizationCap"]["usedBytes"], 7000)
        self.assertEqual(response.data["organizationCap"]["reservedBytes"], 500)

    def test_delete_my_drive_requires_exact_phrase_and_current_password(self):
        response = self.client.post(
            reverse("api-delete-my-drive-data"),
            {"confirmation": "DELETE MY DRIVE", "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            reverse("api-delete-my-drive-data"),
            {"confirmation": "delete my drive", "password": "Correct-password-123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_successful_delete_targets_only_private_my_drive_and_keeps_audit(self):
        folder = Folder.objects.create(
            tenant=self.tenant,
            workspace=self.workspace,
            owner=self.user,
            folder_name="Delete me",
        )
        drive_file = File.objects.create(
            tenant=self.tenant,
            workspace=self.workspace,
            owner=self.user,
            folder=folder,
            file_name="private.txt",
            file_path="uploads/private.txt.enc",
            file_size=12,
            mime_type="text/plain",
        )
        other_folder = Folder.objects.create(
            tenant=self.other_tenant,
            workspace=get_default_workspace(self.other_tenant),
            owner=self.other,
            folder_name="Keep me",
        )
        shared_workspace = Workspace.objects.create(
            tenant=self.tenant,
            name="Shared project",
            slug="shared-project",
            created_by=self.user,
        )
        shared_file = File.objects.create(
            tenant=self.tenant,
            workspace=shared_workspace,
            owner=self.user,
            file_name="shared-project.txt",
            file_path="uploads/shared-project.txt.enc",
            file_size=13,
            mime_type="text/plain",
        )

        def fake_permanent_delete(files):
            files = list(files)
            ids = [item.pk for item in files]
            File.objects.filter(pk__in=ids).delete()
            return len(ids)

        with patch("accounts.settings_api.permanently_delete_files", side_effect=fake_permanent_delete) as delete_mock:
            response = self.client.post(
                reverse("api-delete-my-drive-data"),
                {"confirmation": "DELETE MY DRIVE", "password": "Correct-password-123!"},
                format="json",
            )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["filesDeleted"], 1)
        self.assertTrue(response.data["auditLogRetained"])
        passed_files = list(delete_mock.call_args.args[0])
        self.assertEqual([item.pk for item in passed_files], [drive_file.pk])
        self.assertFalse(File.objects.filter(pk=drive_file.pk).exists())
        self.assertFalse(Folder.objects.filter(pk=folder.pk).exists())
        self.assertTrue(Folder.objects.filter(pk=other_folder.pk).exists())
        self.assertTrue(File.objects.filter(pk=shared_file.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(
            user=self.user,
            workspace=self.workspace,
            action=ActivityLog.Action.DELETE_MY_DRIVE_DATA,
        ).exists())
