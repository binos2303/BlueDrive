"""Regression coverage for session scope, operational visibility and audit lookup."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import PlatformAdminAuditEvent, PlatformAdminIdentity, TrackedAccountSession
from files.models import UploadFinalizationJob, UploadSession


class AdminBusinessReviewTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.root = users.objects.create_superuser(username="review-root", email="review-root@example.test", password="test-secret-123!")
        self.operator = users.objects.create_user(username="review-operator", is_staff=True)
        PlatformAdminIdentity.objects.create(user=self.operator, invited_by=self.root, status="active")
        self.staff = users.objects.create_user(username="unregistered-staff", is_staff=True)
        self.user = users.objects.create_user(username="review-member")
        self.client.force_login(self.root)
        self.now = timezone.now()

    def observe(self, user):
        browser = Client()
        browser.force_login(user)
        TrackedAccountSession.objects.get_or_create(
            session_id=browser.session.session_key, defaults={"user": user, "user_agent": "Review fixture"},
        )

    def test_user_session_scope_excludes_all_protected_staff_accounts(self):
        for user in (self.root, self.operator, self.staff, self.user):
            self.observe(user)
        response = self.client.get(reverse("api-admin-sessions"), {"scope": "users"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["user_id"] for row in response.json()["results"]}, {self.user.pk})

    def test_admin_sessions_include_dedicated_platform_admins_with_correct_type(self):
        for user in (self.root, self.operator, self.staff, self.user):
            self.observe(user)
        response = self.client.get(reverse("api-admin-sessions"), {"scope": "admins"})
        rows = response.json()["results"]
        self.assertEqual({row["user_id"] for row in rows}, {self.root.pk, self.operator.pk})
        operator = next(row for row in rows if row["user_id"] == self.operator.pk)
        self.assertEqual(operator["account_type"], "admin")
        self.assertFalse(operator["can_revoke"])

    def upload_job(self, state, job_state, age_minutes):
        workspace = self.user.personal_tenant.workspaces.get(is_default=True)
        upload = UploadSession.objects.create(
            tenant=self.user.personal_tenant, workspace=workspace, initiated_by=self.user,
            client_name="Review.txt", expected_size_bytes=1, state=state,
            expires_at=self.now + timedelta(hours=1), object_key="staging/private-review-reference",
        )
        job = UploadFinalizationJob.objects.create(upload_session=upload, state=job_state)
        UploadFinalizationJob.objects.filter(pk=job.pk).update(updated_at=self.now - timedelta(minutes=age_minutes))

    def test_overview_reports_actual_job_backlog_without_storage_references(self):
        self.upload_job("verifying", "pending", 5)
        self.upload_job("scanning", "processing", 11)
        self.upload_job("failed", "failed", 20)
        self.upload_job("available", "done", 30)
        with patch("accounts.admin_api.timezone.now", return_value=self.now):
            response = self.client.get(reverse("api-admin-overview"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["uploads"], {
            "pending_jobs": 1, "processing_jobs": 1, "failed_jobs": 1,
            "stale_processing_jobs": 1, "verifying_uploads": 1, "scanning_uploads": 1,
            "oldest_active_job_at": (self.now - timedelta(minutes=11)).isoformat(),
        })
        self.assertNotIn("private-review-reference", response.content.decode())
        self.assertEqual(response.json()["health"]["storage"], "not_monitored")

    def test_empty_backlog_is_zero_and_does_not_claim_worker_liveness(self):
        response = self.client.get(reverse("api-admin-overview"))
        self.assertEqual(response.json()["uploads"]["pending_jobs"], 0)
        self.assertEqual(response.json()["uploads"]["stale_processing_jobs"], 0)
        self.assertIsNone(response.json()["uploads"]["oldest_active_job_at"])
        self.assertNotIn("worker_online", response.json())

    def test_ordinary_user_cannot_read_operational_metrics(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("api-admin-overview")).status_code, 403)

    def test_audit_can_find_reason_and_file_id_without_searching_private_metadata(self):
        event = PlatformAdminAuditEvent.objects.create(
            actor=self.root, target_user=self.user, action="file.trash",
            reason="Investigated duplicate storage entry",
            metadata={"file_id": 123, "private_reference": "do-not-project-this-value"},
        )
        for query in ("duplicate storage", "123"):
            response = self.client.get(reverse("api-admin-audit"), {"q": query})
            self.assertEqual(response.status_code, 200)
            self.assertEqual([row["id"] for row in response.json()["results"]], [str(event.pk)])
            self.assertNotIn("do-not-project-this-value", response.content.decode())
        response = self.client.get(reverse("api-admin-audit"), {"q": "do-not-project-this-value"})
        self.assertEqual(response.json()["count"], 0)
