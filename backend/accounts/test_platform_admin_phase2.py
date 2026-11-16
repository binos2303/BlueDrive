"""Phase 02 platform admin behavior; run with Django's database test runner.

    python manage.py test accounts.test_platform_admin_phase2
"""
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import PlatformAdminAuditEvent, TrackedAccountSession


class PlatformAdminPhase02Tests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="platform-operator", email="operator@example.test", password="Strong-test-password-123!"
        )
        self.user = User.objects.create_user(
            username="regular-person", email="regular@example.test", password="Another-test-password-123!"
        )
        self.other = User.objects.create_user(
            username="regular-other", email="other@example.test", password="Another-test-password-456!"
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.admin)
        csrf_response = self.client.get(reverse("api-csrf"))
        self.csrf_header = {"HTTP_X_CSRFTOKEN": csrf_response.data["csrfToken"]}

    def post(self, route, payload=None, **kwargs):
        return self.client.post(route, payload or {"reason": "Requested by security review"},
                                format="json", **(kwargs or self.csrf_header))

    def test_suspend_disables_user_and_revokes_old_db_session(self):
        old_client = Client()
        old_client.force_login(self.user)
        old_key = old_client.session.session_key
        self.assertTrue(Session.objects.filter(session_key=old_key).exists())
        response = self.post(reverse("api-admin-user-suspend", args=[self.user.pk]))
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
        event = PlatformAdminAuditEvent.objects.get(action="user.suspend")
        self.assertEqual(event.actor_id, self.admin.pk)
        self.assertEqual(event.target_user_id, self.user.pk)

    def test_reactivate_restores_login_not_old_sessions(self):
        old_client = Client()
        old_client.force_login(self.user)
        old_key = old_client.session.session_key
        self.assertEqual(self.post(reverse("api-admin-user-suspend", args=[self.user.pk])).status_code, 200)
        response = self.post(reverse("api-admin-user-reactivate", args=[self.user.pk]),
                             {"reason": "Identity reverified by support"})
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
        self.assertEqual(PlatformAdminAuditEvent.objects.count(), 2)

    def test_admin_and_staff_accounts_are_protected(self):
        result = self.post(reverse("api-admin-user-suspend", args=[self.admin.pk]))
        self.assertEqual(result.status_code, 403)
        self.other.is_staff = True
        self.other.save(update_fields=["is_staff"])
        result = self.post(reverse("api-admin-user-suspend", args=[self.other.pk]))
        self.assertEqual(result.status_code, 403)
        self.assertFalse(PlatformAdminAuditEvent.objects.exists())

    def test_reason_and_csrf_are_required(self):
        missing_csrf = self.client.post(reverse("api-admin-user-suspend", args=[self.user.pk]),
                                        {"reason": "Legitimate reason"}, format="json")
        self.assertEqual(missing_csrf.status_code, 403)
        short_reason = self.post(reverse("api-admin-user-suspend", args=[self.user.pk]),
                                 {"reason": "bad"})
        self.assertEqual(short_reason.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertFalse(PlatformAdminAuditEvent.objects.exists())

    def test_normal_user_cannot_read_or_mutate_platform_admin_api(self):
        outsider = APIClient(enforce_csrf_checks=True)
        outsider.force_login(self.other)
        self.assertEqual(outsider.get(reverse("api-admin-users")).status_code, 403)
        self.assertEqual(outsider.get(reverse("api-admin-audit")).status_code, 403)
        self.assertEqual(outsider.post(reverse("api-admin-user-suspend", args=[self.user.pk]),
                                      {"reason": "Not authorized"}, format="json").status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_observed_session_can_be_listed_and_revoked(self):
        other_client = Client()
        other_client.force_login(self.user)
        key = other_client.session.session_key
        self.assertEqual(other_client.get(reverse("api-current-account")).status_code, 200)
        session = TrackedAccountSession.objects.get(user=self.user)
        self.assertEqual(session.session_id, key)
        listed = self.client.get(reverse("api-admin-sessions"))
        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertIn(str(session.pk), [row["id"] for row in listed.data["results"]])
        revoked = self.post(reverse("api-admin-session-revoke", args=[session.pk]),
                            {"reason": "User requested logout"})
        self.assertEqual(revoked.status_code, 200, revoked.content)
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertFalse(TrackedAccountSession.objects.filter(pk=session.pk).exists())
        self.assertEqual(PlatformAdminAuditEvent.objects.filter(action="session.revoke").count(), 1)

    def test_audit_history_tracks_the_actor_and_reason(self):
        self.post(reverse("api-admin-user-suspend", args=[self.user.pk]),
                  {"reason": "Excessive suspicious uploads"})
        response = self.client.get(reverse("api-admin-audit"))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["actor"], "platform-operator")
        self.assertEqual(row["target"], "regular-person")
        self.assertEqual(row["reason"], "Excessive suspicious uploads")
