"""API regression coverage for read-only User Activity and Admin Audit pages.

Run with: python manage.py test accounts.test_platform_admin_logs -v 2
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from logs.models import ActivityLog
from .models import PlatformAdminAuditEvent, PlatformAdminIdentity


class PlatformLogDirectoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.super_admin = User.objects.create_superuser(
            username="logs-super-admin", email="logs-admin@example.test", password="Admin-Test-Password-2026!"
        )
        self.member = User.objects.create_user(
            username="logs-member", email="logs-member@example.test", password="User-Test-Password-2026!"
        )
        self.admin_user = User.objects.create_user(
            username="logs-regular-admin", email="regular-admin@example.test",
            password="Admin-Test-Password-2026!", is_staff=True, is_active=True,
        )
        PlatformAdminIdentity.objects.create(
            user=self.admin_user, invited_by=self.super_admin,
            status=PlatformAdminIdentity.Status.ACTIVE,
        )
        self.activity = ActivityLog.objects.create(
            user=self.member,
            action=ActivityLog.Action.UPLOAD,
            description="Private search phrase or file details should not be exposed",
            metadata={"private_token": "DO_NOT_DISCLOSE"},
        )
        self.admin_audit = PlatformAdminAuditEvent.objects.create(
            actor=self.super_admin, target_user=self.member,
            action=PlatformAdminAuditEvent.Action.SUSPEND,
            reason="Test administrator policy review",
            metadata={"session_key": "DO_NOT_DISCLOSE"},
        )

    def test_previous_search_events_are_not_shown_or_offered_as_filters(self):
        legacy_search = ActivityLog.objects.create(
            user=self.member, action=ActivityLog.Action.SEARCH,
            description="Searched workspace files.",
        )
        self.client.force_login(self.super_admin)
        response = self.client.get("/accounts/api/admin/activity/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertNotIn(str(legacy_search.pk), {row["id"] for row in response.json()["results"]})
        self.assertNotIn(ActivityLog.Action.SEARCH, {a["value"] for a in response.json()["actions"]})
        self.assertTrue(ActivityLog.objects.filter(pk=legacy_search.pk).exists())

    def test_regular_user_cannot_read_platform_logs(self):
        self.client.force_login(self.member)
        for path in ("/accounts/api/admin/activity/", "/accounts/api/admin/audit/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403)

    def test_unauthed_users_cannot_read_platform_logs(self):
        for path in ("/accounts/api/admin/activity/", "/accounts/api/admin/audit/"):
            response = self.client.get(path)
            self.assertIn(response.status_code, (401, 403))

    def test_user_activity_search_filter_and_privacy(self):
        self.client.force_login(self.super_admin)
        response = self.client.get("/accounts/api/admin/activity/", {
            "q": "logs-member", "scope": "unassigned", "action": "UPLOAD",
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["user"], "logs-member")
        self.assertEqual(body["results"][0]["action"], "UPLOAD")
        self.assertNotIn("metadata", body["results"][0])
        self.assertNotIn("description", body["results"][0])
        self.assertNotIn("DO_NOT_DISCLOSE", response.content.decode())
        self.assertNotIn("Private search phrase", response.content.decode())
        self.assertEqual(self.client.get("/accounts/api/admin/activity/", {"scope": "organization"}).json()["count"], 0)
        self.assertEqual(self.client.post("/accounts/api/admin/activity/").status_code, 405)

    def test_share_details_are_whitelisted_and_old_events_are_unknown(self):
        ActivityLog.objects.create(
            user=self.member, action=ActivityLog.Action.SHARE,
            metadata={
                "operation": "permission_changed", "recipient_email": "recipient@example.test",
                "recipient_username": "recipient", "permission": "editor",
                "previous_permission": "viewer", "resource_names": ["report.pdf"],
                "resource_kinds": ["file"], "shared_count": 1,
                "internal_secret": "NEVER_EXPOSE_THIS",
            },
        )
        ActivityLog.objects.create(user=self.member, action=ActivityLog.Action.SHARE, description="Old legacy share")
        self.client.force_login(self.super_admin)
        response = self.client.get("/accounts/api/admin/activity/", {"action": "SHARE"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        entries = response.json()["results"]
        detailed = next(row for row in entries if row["share"]["operation"] == "permission_changed")
        self.assertEqual(detailed["share"]["recipient"], "recipient@example.test")
        self.assertEqual(detailed["share"]["previous_permission"], "viewer")
        self.assertEqual(detailed["share"]["resources"], ["report.pdf"])
        self.assertNotIn("NEVER_EXPOSE_THIS", response.content.decode())
        legacy = next(row for row in entries if row["share"]["operation"] == "unknown")
        self.assertEqual(legacy["share"]["recipient"], "")

    def test_admin_audit_actions_and_privacy(self):
        self.client.force_login(self.admin_user)
        response = self.client.get("/accounts/api/admin/audit/", {
            "action": "user.suspend", "q": "logs-super-admin",
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 1)
        event = body["results"][0]
        self.assertEqual(event["actor"], "logs-super-admin")
        self.assertEqual(event["target"], "logs-member")
        self.assertEqual(event["reason"], "Test administrator policy review")
        self.assertNotIn("metadata", event)
        self.assertNotIn("DO_NOT_DISCLOSE", response.content.decode())
        self.assertTrue(any(action["value"] == "admin.invite" for action in body["actions"]))
        self.assertEqual(self.client.post("/accounts/api/admin/audit/").status_code, 405)

    def test_bad_filters_rejected_and_date_filter_works(self):
        self.client.force_login(self.super_admin)
        for endpoint in ("activity", "audit"):
            url = f"/accounts/api/admin/{endpoint}/"
            self.assertEqual(self.client.get(url, {"action": "nonexistent"}).status_code, 400)
            self.assertEqual(self.client.get(url, {"from": "2026-02-31"}).status_code, 400)
            self.assertEqual(self.client.get(url, {"from": "2026-10-25", "to": "2026-10-24"}).status_code, 400)
            self.assertEqual(self.client.get(url, {"page": "not-a-number"}).status_code, 400)
            self.assertEqual(self.client.get(url, {"from": "2099-01-01"}).json()["count"], 0)
