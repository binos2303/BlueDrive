"""Sprint 3.2: profile identity, password changes and self-service sessions."""
import json

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import TrackedAccountSession

User = get_user_model()
PASSWORD = "A-valid-test-password-123!"
NEW_PASSWORD = "A-different-strong-password-456!"


class AccountSecurityApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="security-user", email="security@example.test", password=PASSWORD,
        )
        self.other = User.objects.create_user(
            username="security-other", email="other@example.test", password=PASSWORD,
        )
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        response = self.client.get(reverse("api-csrf"))
        self.csrf = {"HTTP_X_CSRFTOKEN": response.json()["csrfToken"]}

    def mutate(self, path, data, *, method="post", client=None, with_csrf=True):
        client = client or self.client
        return getattr(client, method)(
            path, data=json.dumps(data), content_type="application/json",
            **(self.csrf if with_csrf else {}),
        )

    def test_change_password_requires_csrf_and_current_password(self):
        url = reverse("api-me-change-password")
        payload = {"old_password": PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}
        self.assertEqual(self.mutate(url, payload, with_csrf=False).status_code, 403)
        self.assertEqual(self.mutate(url, {**payload, "old_password": "wrong"}).status_code, 400)
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_change_password_retains_current_and_revokes_other_and_legacy_sessions(self):
        tracked = Client()
        tracked.force_login(self.user)
        tracked_key = tracked.session.session_key
        tracked.get(reverse("api-current-account"))
        self.assertTrue(TrackedAccountSession.objects.filter(session_id=tracked_key).exists())
        legacy = Client()
        legacy.force_login(self.user)
        legacy_key = legacy.session.session_key
        self.assertFalse(TrackedAccountSession.objects.filter(session_id=legacy_key).exists())

        response = self.mutate(reverse("api-me-change-password"), {
            "old_password": PASSWORD, "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertGreaterEqual(response.json()["otherSessionsRevoked"], 2)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertFalse(self.user.check_password(PASSWORD))
        self.assertFalse(Session.objects.filter(pk=tracked_key).exists())
        self.assertFalse(Session.objects.filter(pk=legacy_key).exists())
        self.assertEqual(self.client.get(reverse("api-current-account")).status_code, 200)
        self.assertNotEqual(self.client.session.session_key, tracked_key)
        self.assertEqual(tracked.get(reverse("api-current-account")).status_code, 403)

    def test_change_password_validates_confirm_and_django_policy(self):
        url = reverse("api-me-change-password")
        self.assertEqual(self.mutate(url, {
            "old_password": PASSWORD, "new_password1": "tiny", "new_password2": "tiny",
        }).status_code, 400)
        self.assertEqual(self.mutate(url, {
            "old_password": PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": "mismatch",
        }).status_code, 400)
        self.assertEqual(self.mutate(url, {
            "old_password": PASSWORD, "new_password1": PASSWORD, "new_password2": PASSWORD,
        }).status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_session_listing_only_shows_own_observed_sessions_and_no_session_keys(self):
        peer = Client()
        peer.force_login(self.user)
        peer.get(reverse("api-current-account"))
        stranger = Client()
        stranger.force_login(self.other)
        stranger.get(reverse("api-current-account"))
        response = self.client.get(reverse("api-me-sessions"))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertTrue(any(row["current"] for row in data["sessions"]))
        self.assertNotIn("session_key", response.content.decode())
        self.assertNotIn(peer.session.session_key, response.content.decode())
        self.assertEqual(self.client.get(reverse("api-me-sessions") + "?page=-1").status_code, 400)
        self.assertEqual(self.client.get(reverse("api-me-sessions") + "?page=nope").status_code, 400)

    def test_revoke_one_session_checks_password_csrf_and_user_ownership(self):
        peer = Client()
        peer.force_login(self.user)
        peer.get(reverse("api-current-account"))
        row = TrackedAccountSession.objects.get(session_id=peer.session.session_key)
        stranger = Client()
        stranger.force_login(self.other)
        stranger.get(reverse("api-current-account"))
        other_row = TrackedAccountSession.objects.get(user=self.other)
        url = reverse("api-me-revoke-session", args=[row.pk])
        self.assertEqual(self.mutate(url, {"current_password": PASSWORD}, method="delete", with_csrf=False).status_code, 403)
        self.assertEqual(self.mutate(url, {"current_password": "wrong"}, method="delete").status_code, 403)
        self.assertEqual(self.mutate(reverse("api-me-revoke-session", args=[other_row.pk]),
                                     {"current_password": PASSWORD}, method="delete").status_code, 404)
        response = self.mutate(url, {"current_password": PASSWORD}, method="delete")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["signedOut"])
        self.assertFalse(Session.objects.filter(pk=row.session_id).exists())
        self.assertEqual(self.client.get(reverse("api-current-account")).status_code, 200)

    def test_revoke_current_session_logs_out(self):
        current = self.client.get(reverse("api-me-sessions")).json()["sessions"]
        row = next(item for item in current if item["current"])
        result = self.mutate(reverse("api-me-revoke-session", args=[row["id"]]),
                             {"current_password": PASSWORD}, method="delete")
        self.assertEqual(result.status_code, 200, result.content)
        self.assertTrue(result.json()["signedOut"])
        self.assertEqual(self.client.get(reverse("api-current-account")).status_code, 403)

    def test_revoke_others_includes_sessions_created_before_tracking(self):
        other_device = Client()
        other_device.force_login(self.user)
        old_key = other_device.session.session_key
        self.assertFalse(TrackedAccountSession.objects.filter(session_id=old_key).exists())
        url = reverse("api-me-revoke-other-sessions")
        self.assertEqual(self.mutate(url, {}, with_csrf=True).status_code, 400)
        self.assertEqual(self.mutate(url, {"current_password": "wrong"}).status_code, 403)
        result = self.mutate(url, {"current_password": PASSWORD})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertGreaterEqual(result.json()["revoked"], 1)
        self.assertFalse(Session.objects.filter(pk=old_key).exists())
        self.assertEqual(self.client.get(reverse("api-current-account")).status_code, 200)

    def test_profile_email_requires_password_rejects_duplicates_and_unknown_fields(self):
        url = reverse("api-current-account")
        self.assertEqual(self.mutate(url, {"email": "fresh@example.test"}, method="patch").status_code, 400)
        self.assertEqual(self.mutate(url, {"email": "fresh@example.test", "current_password": "wrong"}, method="patch").status_code, 403)
        self.assertEqual(self.mutate(url, {"email": "OTHER@EXAMPLE.TEST", "current_password": PASSWORD}, method="patch").status_code, 409)
        self.assertEqual(self.mutate(url, {"email": "fresh@example.test", "current_password": PASSWORD, "is_staff": True}, method="patch").status_code, 400)
        success = self.mutate(url, {"email": "fresh@example.test", "current_password": PASSWORD}, method="patch")
        self.assertEqual(success.status_code, 200, success.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "fresh@example.test")
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_profile_email_csrf_is_enforced(self):
        result = self.mutate(reverse("api-current-account"),
                             {"email": "x@example.test", "current_password": PASSWORD},
                             method="patch", with_csrf=False)
        self.assertEqual(result.status_code, 403)

    @override_settings(SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies")
    def test_session_management_avoids_misleading_results_for_non_db_backends(self):
        cookie_client = Client()
        cookie_client.force_login(self.user)
        self.assertEqual(cookie_client.get(reverse("api-me-sessions")).status_code, 503)

    def test_unauthenticated_security_endpoints_do_not_expose_data(self):
        anonymous = Client()
        self.assertIn(anonymous.get(reverse("api-me-sessions")).status_code, (401, 403))
        self.assertIn(anonymous.post(reverse("api-me-change-password"),
                                     data=json.dumps({}), content_type="application/json").status_code, (401, 403))
