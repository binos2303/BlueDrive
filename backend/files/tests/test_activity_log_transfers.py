"""Transfer events are recorded exactly once for successful file publication."""

import hashlib
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from files.finalization import finalize_verified_upload
from files.models import UploadSession
from logs.models import ActivityLog


class MultipartUploadActivityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="transfer-audit-owner", password="test-secret-123!"
        )
        self.content = b"verified multipart content"
        self.session = UploadSession.objects.create(
            tenant=self.user.personal_tenant,
            initiated_by=self.user,
            client_name="report.txt",
            expected_size_bytes=len(self.content),
            expected_sha256=hashlib.sha256(self.content).hexdigest(),
            object_key="staging/audit-test",
            state=UploadSession.State.VERIFYING,
            expires_at=timezone.now() + timedelta(hours=1),
        )

    @patch("files.finalization.finalize_upload_quota")
    @patch("files.finalization.get_storage_adapter")
    def test_successful_upload_is_logged_once_and_visible_in_personal_history(self, adapter_factory, quota):
        storage = adapter_factory.return_value
        storage.create_object_key.return_value = "primary/audit-test"
        result = finalize_verified_upload(self.session, self.content, self.user)
        self.assertEqual(result["state"], UploadSession.State.AVAILABLE)
        self.assertEqual(ActivityLog.objects.filter(
            user=self.user, action=ActivityLog.Action.UPLOAD,
        ).count(), 1)
        event = ActivityLog.objects.get(user=self.user, action=ActivityLog.Action.UPLOAD)
        self.assertEqual(event.workspace_id, self.session.workspace_id)
        self.assertEqual(event.metadata["size_bytes"], len(self.content))
        self.assertEqual(event.metadata["resource_name"], "report.txt")
        self.assertEqual(event.object_id, result["file_id"])
        quota.assert_called_once()

        again = finalize_verified_upload(self.session, self.content, self.user)
        self.assertEqual(again["file_id"], result["file_id"])
        self.assertEqual(ActivityLog.objects.filter(
            user=self.user, action=ActivityLog.Action.UPLOAD,
        ).count(), 1)
        storage.put_object.assert_called_once()

        self.client.force_login(self.user)
        response = self.client.get(reverse("api-my-activity"), {"action": "UPLOAD"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["action"] for row in response.json()["events"]], ["UPLOAD"])

    @patch("files.finalization.get_storage_adapter")
    def test_failed_upload_does_not_emit_success_event(self, adapter_factory):
        self.session.state = UploadSession.State.FAILED
        self.session.save(update_fields=["state", "updated_at"])
        with self.assertRaises(ValueError):
            finalize_verified_upload(self.session, self.content, self.user)
        self.assertFalse(ActivityLog.objects.filter(
            user=self.user, action=ActivityLog.Action.UPLOAD,
        ).exists())
        adapter_factory.assert_not_called()
