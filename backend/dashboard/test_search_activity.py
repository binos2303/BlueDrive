"""Search history remains available without cluttering the activity audit stream."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.access import get_default_workspace
from accounts.services import get_personal_tenant
from logs.models import ActivityLog, SearchHistory


class SearchActivityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="search-member", password="sample-strong-password-123!"
        )
        self.tenant = get_personal_tenant(self.user)
        self.workspace = get_default_workspace(self.tenant)
        self.client.force_login(self.user)

    def test_workspace_search_preserves_results_and_history_without_activity_log(self):
        response = self.client.get(reverse("drive_items_api"), {"q": "sample"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])
        self.assertTrue(SearchHistory.objects.filter(user=self.user, query="sample").exists())
        self.assertFalse(ActivityLog.objects.filter(user=self.user, action=ActivityLog.Action.SEARCH).exists())

    def test_shared_search_preserves_history_without_activity_log(self):
        response = self.client.get(reverse("drive_items_api"), {"view": "shared", "q": "document"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(SearchHistory.objects.filter(user=self.user, query="document").exists())
        self.assertFalse(ActivityLog.objects.filter(user=self.user, action=ActivityLog.Action.SEARCH).exists())

    def test_previous_search_activity_hidden_but_not_deleted(self):
        old = ActivityLog.objects.create(
            user=self.user, tenant=self.tenant, workspace=self.workspace,
            action=ActivityLog.Action.SEARCH, description="Searched workspace files.",
        )
        ActivityLog.objects.create(
            user=self.user, tenant=self.tenant, workspace=self.workspace,
            action=ActivityLog.Action.CREATE_WORKSPACE, description="Created workspace.",
        )
        response = self.client.get(reverse("api-my-activity"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(ActivityLog.Action.SEARCH, {row["action"] for row in response.json()["events"]})
        self.assertTrue(ActivityLog.objects.filter(pk=old.pk).exists())
