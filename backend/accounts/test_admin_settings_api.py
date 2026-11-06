"""Sprint 4.5: real persisted admin settings and security controls."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import (
    PlatformAdminAuditEvent, PlatformAdminIdentity, PlatformConsoleSettings,
)


class AdminSettingsAPITests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser(
            username="settings-root", email="root-settings@example.test",
            password="Strong-root-pass-123!",
        )
        self.platform = User.objects.create_user(
            username="settings-platform", email="platform-settings@example.test",
            password="Strong-platform-pass-123!", is_staff=True,
        )
        PlatformAdminIdentity.objects.create(
            user=self.platform, invited_by=self.root,
            status=PlatformAdminIdentity.Status.ACTIVE,
        )
        self.staff_without_identity = User.objects.create_user(
            username="settings-rogue", password="Strong-password-123!", is_staff=True,
        )
        self.regular = User.objects.create_user(
            username="settings-user", password="Strong-password-123!",
        )
        self.url = reverse("api-admin-settings")
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.root)
        self.csrf = {
            "HTTP_X_CSRFTOKEN": self.client.get(reverse("api-csrf")).data["csrfToken"],
        }

    def update(self, name="BlueDrive Cloud", reason="Approved console rename", revision=0, **kwargs):
        return self.client.patch(
            self.url, {"display_name": name, "reason": reason, "revision": revision, **kwargs},
            format="json", **self.csrf,
        )

    def test_defaults_are_read_only_until_explicit_change(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["display_name"], "BlueDrive")
        self.assertEqual(response.data["revision"], 0)
        self.assertTrue(response.data["can_edit"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(PlatformConsoleSettings.objects.count(), 0)

    @override_settings(SESSION_COOKIE_AGE=3600, SESSION_EXPIRE_AT_BROWSER_CLOSE=True, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
    def test_effective_django_runtime_security_is_read_only(self):
        data = self.client.get(self.url).data["effective_security"]
        self.assertEqual(data["session_cookie_age_seconds"], 3600)
        self.assertTrue(data["expire_at_browser_close"])
        self.assertFalse(data["session_cookie_secure"])
        self.assertEqual(data["admin_audit"], "enforced_for_supported_actions")
        self.assertEqual(data["maintenance_mode"], "not_configured")
        self.assertFalse({"secret_key", "database_url", "object_storage_credentials"} & set(data))

    def test_superadmin_can_save_and_change_is_audited(self):
        response = self.update()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["display_name"], "BlueDrive Cloud")
        self.assertEqual(response.data["revision"], 1)
        self.assertEqual(self.client.get(self.url).data["display_name"], "BlueDrive Cloud")
        self.assertEqual(PlatformConsoleSettings.objects.count(), 1)
        event = PlatformAdminAuditEvent.objects.get()
        self.assertEqual(event.action, PlatformAdminAuditEvent.Action.SETTINGS_UPDATE)
        self.assertEqual(event.actor, self.root)
        self.assertEqual(event.target_user, self.root)
        self.assertEqual(event.reason, "Approved console rename")
        self.assertEqual(event.metadata, {
            "field": "display_name", "before": "BlueDrive", "after": "BlueDrive Cloud",
        })
        audit_page = self.client.get(reverse("api-admin-audit"))
        self.assertEqual(audit_page.status_code, 200)
        self.assertEqual(audit_page.data["results"][0]["action"], "settings.update")

    def test_noop_does_not_create_audit(self):
        response = self.update(name="BlueDrive")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["revision"], 0)
        self.assertFalse(PlatformAdminAuditEvent.objects.exists())
        self.assertEqual(self.update(name="BlueDrive Cloud").status_code, 200)
        self.assertEqual(self.update(name="BlueDrive Cloud", revision=1).status_code, 200)
        self.assertEqual(PlatformAdminAuditEvent.objects.count(), 1)

    def test_conflicting_revision_returns_409_without_changing_row(self):
        self.assertEqual(self.update().status_code, 200)
        response = self.update(name="Other Console", revision=0)
        self.assertEqual(response.status_code, 409)
        row = PlatformConsoleSettings.objects.get(pk=1)
        self.assertEqual(row.display_name, "BlueDrive Cloud")
        self.assertEqual(row.revision, 1)
        self.assertEqual(PlatformAdminAuditEvent.objects.count(), 1)

    def test_platform_admin_can_view_but_not_change(self):
        self.client.force_login(self.platform)
        self.csrf = {"HTTP_X_CSRFTOKEN": self.client.get(reverse("api-csrf")).data["csrfToken"]}
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["can_edit"])
        self.assertEqual(self.update().status_code, 403)
        self.assertFalse(PlatformAdminAuditEvent.objects.exists())

    def test_regular_unregistered_staff_and_unauthenticated_denied(self):
        for user in (self.regular, self.staff_without_identity):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.csrf = {"HTTP_X_CSRFTOKEN": self.client.get(reverse("api-csrf")).data["csrfToken"]}
                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(self.update().status_code, 403)
        self.client.logout()
        self.assertIn(self.client.get(self.url).status_code, (401, 403))
        self.assertIn(self.update().status_code, (401, 403))

    def test_csrf_required_for_change(self):
        response = self.client.patch(
            self.url,
            {"display_name": "Other Console", "reason": "Approved for migration", "revision": 0},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(PlatformConsoleSettings.objects.count(), 0)

    def test_strict_validation_rejects_extra_keys_and_wrong_types(self):
        for payload in (
            {"display_name": "New Label", "reason": "Approved for migration", "revision": 0, "maintenance": True},
            {"display_name": "New Label", "reason": "Approved for migration"},
            {"display_name": "New Label", "reason": "Approved for migration", "revision": True},
            {"display_name": "New Label", "reason": "Approved for migration", "revision": "0"},
            {"display_name": 123, "reason": "Approved for migration", "revision": 0},
            {"display_name": "New Label", "reason": "short", "revision": 0},
            {"display_name": "\nNew Label", "reason": "Approved for migration", "revision": 0},
            {"display_name": "New Label", "reason": "Approved\nfor migration", "revision": 0},
            {"display_name": " ", "reason": "Approved for migration", "revision": 0},
            {"display_name": "X" * 81, "reason": "Approved for migration", "revision": 0},
        ):
            with self.subTest(payload=payload):
                response = self.client.patch(self.url, payload, format="json", **self.csrf)
                self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(PlatformConsoleSettings.objects.count(), 0)
        self.assertFalse(PlatformAdminAuditEvent.objects.exists())

    def test_post_delete_and_put_not_supported(self):
        self.assertEqual(self.client.post(self.url, {}, format="json", **self.csrf).status_code, 405)
        self.assertEqual(self.client.delete(self.url, **self.csrf).status_code, 405)
        self.assertEqual(self.client.put(self.url, {}, format="json", **self.csrf).status_code, 405)

    def test_audit_failure_rolls_back_change(self):
        with patch("accounts.admin_settings_api.PlatformAdminAuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.update()
        self.assertFalse(PlatformConsoleSettings.objects.exists())

    def test_singleton_db_check_prevents_extra_settings(self):
        self.assertEqual(self.update().status_code, 200)
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PlatformConsoleSettings.objects.create(pk=2, display_name="Extra")
        self.assertEqual(PlatformConsoleSettings.objects.count(), 1)
