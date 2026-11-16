"""Ensure private history is ordered and paginated without hiding older actions."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from logs.models import ActivityLog, SearchHistory


class ActivityHistoryPaginationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="history-paging-user", password="test-123!")
        self.other = User.objects.create_user(username="history-paging-other", password="test-123!")
        self.client.force_login(self.user)

    def test_activity_is_newest_first_across_pages_and_excludes_search_audit(self):
        older = ActivityLog.objects.create(user=self.user, action=ActivityLog.Action.UPLOAD, description="older upload")
        newer = ActivityLog.objects.create(user=self.user, action=ActivityLog.Action.DOWNLOAD, description="newer download")
        ActivityLog.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=2))
        ActivityLog.objects.create(user=self.user, action=ActivityLog.Action.SEARCH, description="legacy search")
        ActivityLog.objects.create(user=self.other, action=ActivityLog.Action.UPLOAD, description="private other user")
        first = self.client.get(reverse("api-my-activity"), {"limit": "1"}).json()
        second = self.client.get(reverse("api-my-activity"), {"limit": "1", "offset": "1"}).json()
        self.assertEqual([e["id"] for e in first["events"]], [newer.pk])
        self.assertTrue(first["hasMore"])
        self.assertEqual([e["id"] for e in second["events"]], [older.pk])
        self.assertFalse(second["hasMore"])

    def test_search_history_is_private_newest_first_and_paginated(self):
        older = SearchHistory.objects.create(user=self.user, query="old keyword")
        newer = SearchHistory.objects.create(user=self.user, query="new keyword")
        SearchHistory.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=2))
        SearchHistory.objects.create(user=self.other, query="other user search")
        first = self.client.get(reverse("api-my-search-history"), {"limit": "1"}).json()
        second = self.client.get(reverse("api-my-search-history"), {"limit": "1", "offset": "1"}).json()
        self.assertEqual([e["query"] for e in first["items"]], ["new keyword"])
        self.assertTrue(first["hasMore"])
        self.assertEqual([e["query"] for e in second["items"]], ["old keyword"])
        self.assertFalse(second["hasMore"])
