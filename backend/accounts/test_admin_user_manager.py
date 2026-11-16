"""Sprint 4.1: platform User Manager query ordering and session security."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import PlatformAdminAuditEvent, TrackedAccountSession


class AdminUserManagerTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="manager-root", email="root@example.test", password="Strong-admin-pass-123!"
        )
        self.alpha = User.objects.create_user(
            username="alpha", email="alpha@example.test", password="Strong-user-pass-123!"
        )
        self.zulu = User.objects.create_user(
            username="zulu", email="zulu@example.test", password="Strong-user-pass-123!"
        )
        self.unseen = User.objects.create_user(
            username="middle", email="middle@example.test", password="Strong-user-pass-123!"
        )
        now = timezone.now()
        User.objects.filter(pk=self.alpha.pk).update(
            last_login=now - timedelta(days=5), date_joined=now - timedelta(days=20),
        )
        User.objects.filter(pk=self.zulu.pk).update(
            last_login=now - timedelta(days=1), date_joined=now - timedelta(days=10),
        )
        User.objects.filter(pk=self.unseen.pk).update(last_login=None, date_joined=now)
        self.admin_client = APIClient(enforce_csrf_checks=True)
        self.admin_client.force_login(self.admin)
        self.csrf = {
            "HTTP_X_CSRFTOKEN": self.admin_client.get(reverse("api-csrf")).data["csrfToken"]
        }
        self.url = reverse("api-admin-users")

    def users(self, **params):
        return self.admin_client.get(self.url, {"scope": "users", **params})

    def test_recent_and_oldest_signin_place_never_signed_in_last(self):
        recent = self.users(sort="recent_signin")
        self.assertEqual(recent.status_code, 200, recent.data)
        self.assertEqual(recent.data["sort"], "recent_signin")
        self.assertEqual(
            [row["username"] for row in recent.data["results"]],
            ["zulu", "alpha", "middle"],
        )
        oldest = self.users(sort="oldest_signin")
        self.assertEqual(
            [row["username"] for row in oldest.data["results"]],
            ["alpha", "zulu", "middle"],
        )

    def test_join_and_name_sort_are_applied_on_server(self):
        expected = {
            "newest": ["middle", "zulu", "alpha"],
            "oldest": ["alpha", "zulu", "middle"],
            "name_asc": ["alpha", "middle", "zulu"],
            "name_desc": ["zulu", "middle", "alpha"],
        }
        for sort, names in expected.items():
            with self.subTest(sort=sort):
                response = self.users(sort=sort)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual([row["username"] for row in response.data["results"]], names)

    def test_invalid_filters_fail_closed(self):
        for params in ({"sort": "-password"}, {"status": "unknown"}, {"scope": "staff"}):
            with self.subTest(params=params):
                response = self.admin_client.get(self.url, params)
                self.assertEqual(response.status_code, 400, response.data)

    def test_scope_status_and_search_are_server_side(self):
        self.unseen.is_active = False
        self.unseen.save(update_fields=["is_active"])
        response = self.users(status="inactive", q="MIDDLE", sort="name_asc")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.unseen.pk)
        admins = self.admin_client.get(self.url, {"scope": "admins"})
        self.assertEqual(admins.status_code, 200, admins.data)
        self.assertEqual([row["id"] for row in admins.data["results"]], [self.admin.pk])

    def test_sorted_pagination_is_stable_and_no_secrets_are_projected(self):
        User = get_user_model()
        # Directory-only rows do not need full tenant onboarding fixtures.
        User.objects.bulk_create([User(username=f"batch-{i:02d}") for i in range(22)])
        first = self.users(sort="name_asc", page=1)
        second = self.users(sort="name_asc", page=2)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["count"], 25)
        first_ids = [row["id"] for row in first.data["results"]]
        second_ids = [row["id"] for row in second.data["results"]]
        self.assertEqual(len(first_ids), 20)
        self.assertEqual(len(second_ids), 5)
        self.assertFalse(set(first_ids) & set(second_ids))
        for row in first.data["results"]:
            self.assertTrue({"username", "date_joined", "last_login", "recently_online"} <= row.keys())
            self.assertFalse({"password", "session_key", "api_token"} & row.keys())

    def test_regular_user_cannot_view_directory_or_sessions(self):
        ordinary = APIClient()
        ordinary.force_login(self.alpha)
        self.assertEqual(ordinary.get(self.url).status_code, 403)
        self.assertEqual(ordinary.get(reverse("api-admin-sessions")).status_code, 403)

    def test_admin_can_inspect_regular_users_observed_sessions_only(self):
        other_client = Client()
        other_client.force_login(self.alpha)
        self.assertEqual(other_client.get(reverse("api-current-account")).status_code, 200)
        key = other_client.session.session_key
        tracked = TrackedAccountSession.objects.get(session_id=key)
        result = self.admin_client.get(reverse("api-admin-sessions"), {
            "scope": "users", "user_id": str(self.alpha.pk),
        })
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["count"], 1)
        self.assertEqual(result.data["results"][0]["id"], str(tracked.pk))
        self.assertNotIn("session_key", result.data["results"][0])
        self.assertNotIn(key, str(result.data))

    def test_revoke_requires_csrf_and_reason_and_records_audit(self):
        other_client = Client()
        other_client.force_login(self.alpha)
        key = other_client.session.session_key
        other_client.get(reverse("api-current-account"))
        tracked = TrackedAccountSession.objects.get(session_id=key)
        endpoint = reverse("api-admin-session-revoke", args=[tracked.pk])
        no_csrf = self.admin_client.post(endpoint, {"reason": "User requested a logout"}, format="json")
        self.assertEqual(no_csrf.status_code, 403)
        short_reason = self.admin_client.post(endpoint, {"reason": "short"}, format="json", **self.csrf)
        self.assertEqual(short_reason.status_code, 400)
        self.assertTrue(Session.objects.filter(pk=key).exists())
        result = self.admin_client.post(endpoint, {
            "reason": "User requested a logout",
        }, format="json", **self.csrf)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertFalse(Session.objects.filter(pk=key).exists())
        self.assertEqual(PlatformAdminAuditEvent.objects.filter(
            action=PlatformAdminAuditEvent.Action.REVOKE_SESSION,
            target_user=self.alpha,
        ).count(), 1)

    def test_staff_session_cannot_be_revoked_through_user_manager(self):
        other_client = Client()
        other_client.force_login(self.admin)
        key = other_client.session.session_key
        other_client.get(reverse("api-admin-access"))
        tracked = TrackedAccountSession.objects.get(session_id=key)
        result = self.admin_client.post(reverse("api-admin-session-revoke", args=[tracked.pk]), {
            "reason": "Attempt to revoke protected session",
        }, format="json", **self.csrf)
        self.assertEqual(result.status_code, 403)
        self.assertTrue(Session.objects.filter(pk=key).exists())
