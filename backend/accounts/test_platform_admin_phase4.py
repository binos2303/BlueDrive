"""Phase 04: independent administrator provisioning and security boundary.

Run: python manage.py test accounts.test_platform_admin_phase4 -v 2
"""
from urllib.parse import parse_qs, urlsplit
from datetime import datetime, timedelta
import secrets
from smtplib import SMTPException
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sessions.models import Session
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .models import PlatformAdminAuditEvent, PlatformAdminIdentity, Tenant
from .platform_admin import is_platform_admin, is_platform_super_admin


@override_settings(
    DEBUG=True,
    ADMIN_INVITES_ENABLED=True,
    NEXTJS_FRONTEND_URL="http://localhost:3000",
    DEFAULT_FROM_EMAIL="security@example.test",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class PlatformAdminPhase04Tests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser(
            username="root-operator", email="root@example.test", password="Root-Admin-Test-Password-123!"
        )
        self.normal = User.objects.create_user(
            username="normal-person", email="normal@example.test", password="Regular-Password-Test-123!"
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.root)
        self.csrf_header = {"HTTP_X_CSRFTOKEN": self.client.get(reverse("api-csrf")).data["csrfToken"]}

    def invite(self, username="new-platform-admin", email="new.admin@example.test"):
        return self.client.post(reverse("api-admin-invite"), {
            "username": username, "email": email,
            "reason": "Provision a dedicated security operator account",
        }, format="json", **self.csrf_header)

    def test_super_admin_provisions_separate_inactive_account_without_drive(self):
        response = self.invite()
        self.assertEqual(response.status_code, 201, response.data)
        user = get_user_model().objects.get(username="new-platform-admin")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertFalse(Tenant.objects.filter(personal_owner=user).exists())
        self.assertEqual(user.platform_admin_identity.status, PlatformAdminIdentity.Status.INVITED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("token", response.data)
        event = PlatformAdminAuditEvent.objects.get(action="admin.invite")
        self.assertEqual(event.actor_id, self.root.id)
        self.assertEqual(event.target_user_id, user.id)
        self.assertFalse(is_platform_admin(user))

    def test_invitation_activation_is_one_time_and_stays_non_superuser(self):
        self.assertEqual(self.invite().status_code, 201)
        url = next(line for line in mail.outbox[0].body.splitlines() if "/admin-invite#" in line)
        self.assertFalse(urlsplit(url).query)
        params = parse_qs(urlsplit(url).fragment)
        new_client = APIClient(enforce_csrf_checks=True)
        csrf = new_client.get(reverse("api-csrf")).data["csrfToken"]
        payload = {
            "uid": params["uid"][0], "token": params["token"][0],
            "password1": "Accepted-Admin-Password-2026!",
            "password2": "Accepted-Admin-Password-2026!",
        }
        accepted = new_client.post(reverse("api-admin-invite-accept"), payload, format="json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(accepted.status_code, 200, accepted.data)
        admin = get_user_model().objects.get(username="new-platform-admin")
        self.assertTrue(admin.is_active)
        self.assertTrue(admin.check_password(payload["password1"]))
        self.assertFalse(admin.is_superuser)
        self.assertTrue(is_platform_admin(admin))
        self.assertFalse(is_platform_super_admin(admin))
        self.assertFalse(Tenant.objects.filter(personal_owner=admin).exists())
        replay = new_client.post(reverse("api-admin-invite-accept"), payload, format="json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(replay.status_code, 400)

        standard_admin = APIClient(enforce_csrf_checks=True)
        standard_admin.force_login(admin)
        other_csrf = standard_admin.get(reverse("api-csrf")).data["csrfToken"]
        self.assertEqual(standard_admin.get(reverse("api-admin-access")).status_code, 200)
        self.assertEqual(standard_admin.get(reverse("api-admin-files")).status_code, 200)
        cannot_invite = standard_admin.post(reverse("api-admin-invite"), {
            "username": "another", "email": "another@example.test", "reason": "No permission to provision",
        }, format="json", HTTP_X_CSRFTOKEN=other_csrf)
        self.assertEqual(cannot_invite.status_code, 403)

    def test_normal_user_cannot_invite_and_existing_user_cannot_be_promoted(self):
        conflict = self.invite(username=self.normal.username, email="other@example.test")
        self.assertEqual(conflict.status_code, 409)
        conflict_email = self.invite(username="other-account", email=self.normal.email)
        self.assertEqual(conflict_email.status_code, 409)
        regular = APIClient(enforce_csrf_checks=True)
        regular.force_login(self.normal)
        csrf = regular.get(reverse("api-csrf")).data["csrfToken"]
        denied = regular.post(reverse("api-admin-invite"), {
            "username": "illegal", "email": "illegal@example.test", "reason": "Attempt to gain elevated access",
        }, format="json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(denied.status_code, 403)

    def test_disable_standard_admin_revokes_sessions_but_not_bootstrap_admin(self):
        self.invite()
        user = get_user_model().objects.get(username="new-platform-admin")
        user.platform_admin_identity.status = PlatformAdminIdentity.Status.ACTIVE
        user.platform_admin_identity.save(update_fields=["status"])
        user.is_active = True
        user.set_password("Temporary-Admin-Password-2026!")
        user.save(update_fields=["is_active", "password"])
        logged_in = Client()
        logged_in.force_login(user)
        session_key = logged_in.session.session_key
        self.assertTrue(Session.objects.filter(session_key=session_key).exists())
        response = self.client.post(reverse("api-admin-disable", args=[user.pk]), {
            "reason": "Administrator no longer needs platform access",
        }, format="json", **self.csrf_header)
        self.assertEqual(response.status_code, 200, response.data)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.platform_admin_identity.status, PlatformAdminIdentity.Status.DISABLED)
        self.assertFalse(Session.objects.filter(session_key=session_key).exists())
        self.assertEqual(PlatformAdminAuditEvent.objects.filter(action="admin.disable").count(), 1)
        protected = self.client.post(reverse("api-admin-disable", args=[self.root.pk]), {
            "reason": "Should never disable a Super Admin",
        }, format="json", **self.csrf_header)
        self.assertEqual(protected.status_code, 403)

    def test_reinvite_invalidates_old_link_and_preserves_identity(self):
        self.assertEqual(self.invite().status_code, 201)
        user = get_user_model().objects.get(username="new-platform-admin")
        first_link = next(line for line in mail.outbox[-1].body.splitlines() if "/admin-invite#" in line)
        self.assertFalse(urlsplit(first_link).query)
        first = parse_qs(urlsplit(first_link).fragment)
        response = self.client.post(reverse("api-admin-reinvite", args=[user.pk]), {
            "reason": "The original invitation expired or was not delivered"
        }, format="json", **self.csrf_header)
        self.assertEqual(response.status_code, 200, response.data)
        second_link = next(line for line in mail.outbox[-1].body.splitlines() if "/admin-invite#" in line)
        self.assertFalse(urlsplit(second_link).query)
        second = parse_qs(urlsplit(second_link).fragment)
        self.assertNotEqual(first["token"][0], second["token"][0])
        self.assertEqual(PlatformAdminIdentity.objects.filter(user=user).count(), 1)
        new_client = APIClient(enforce_csrf_checks=True)
        csrf = new_client.get(reverse("api-csrf")).data["csrfToken"]
        payload = {"uid": first["uid"][0], "token": first["token"][0],
                   "password1": "Accepted-Admin-Password-2026!", "password2": "Accepted-Admin-Password-2026!"}
        old_result = new_client.post(reverse("api-admin-invite-accept"), payload,
                                     format="json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(old_result.status_code, 400)
        payload["token"] = second["token"][0]
        new_result = new_client.post(reverse("api-admin-invite-accept"), payload,
                                     format="json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(new_result.status_code, 200, new_result.data)

    @override_settings(ADMIN_INVITES_ENABLED=False)
    def test_invitation_is_disabled_by_default_without_transport(self):
        response = self.invite()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(get_user_model().objects.filter(username="new-platform-admin").exists())

    def test_mutations_require_csrf(self):
        response = self.client.post(reverse("api-admin-invite"), {
            "username": "missing-csrf", "email": "missing@example.test", "reason": "Provision for legitimate security use",
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(get_user_model().objects.filter(username="missing-csrf").exists())

    def test_debug_transport_never_emits_invitation_tokens_to_console_or_file(self):
        for backend in ("console", "filebased", "dummy"):
            with self.subTest(backend=backend), override_settings(
                EMAIL_BACKEND=f"django.core.mail.backends.{backend}.EmailBackend"
            ), patch("accounts.platform_admin_provisioning.send_mail") as send:
                response = self.invite()
                self.assertEqual(response.status_code, 503)
                send.assert_not_called()
        self.assertFalse(get_user_model().objects.filter(username="new-platform-admin").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_delivery_failure_logs_no_token_and_rolls_back_invited_identity(self):
        token = secrets.token_urlsafe(32)
        with patch("accounts.platform_admin_provisioning.default_token_generator.make_token", return_value=token), \
                patch("accounts.platform_admin_provisioning.send_mail", side_effect=SMTPException(token)), \
                self.assertLogs("accounts.platform_admin_provisioning", level="WARNING") as captured:
            response = self.invite()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(token in "\n".join(captured.output))
        self.assertFalse(token.encode() in response.content)
        self.assertFalse(get_user_model().objects.filter(username="new-platform-admin").exists())
        self.assertFalse(PlatformAdminIdentity.objects.exists())

    def test_invalid_expired_and_missing_csrf_tokens_do_not_activate_account(self):
        self.assertEqual(self.invite().status_code, 201)
        user = get_user_model().objects.get(username="new-platform-admin")
        link = next(line for line in mail.outbox[-1].body.splitlines() if "/admin-invite#" in line)
        fields = parse_qs(urlsplit(link).fragment)
        password = secrets.token_urlsafe(32)
        payload = {"uid": fields["uid"][0], "token": fields["token"][0],
                   "password1": password, "password2": password}
        client = APIClient(enforce_csrf_checks=True)
        url = reverse("api-admin-invite-accept")
        self.assertEqual(client.post(url, payload, format="json").status_code, 403)
        csrf = client.get(reverse("api-csrf")).data["csrfToken"]
        invalid = {**payload, "token": "invalid"}
        self.assertEqual(client.post(url, invalid, format="json", HTTP_X_CSRFTOKEN=csrf).status_code, 400)
        past = datetime.now() - timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT + 1)
        with patch.object(default_token_generator, "_now", return_value=past):
            expired = {**payload, "token": default_token_generator.make_token(user)}
        self.assertEqual(client.post(url, expired, format="json", HTTP_X_CSRFTOKEN=csrf).status_code, 400)
        user.refresh_from_db()
        self.assertFalse(user.is_active or user.has_usable_password())
        self.assertFalse(PlatformAdminAuditEvent.objects.filter(action=PlatformAdminAuditEvent.Action.ACCEPT_ADMIN).exists())
