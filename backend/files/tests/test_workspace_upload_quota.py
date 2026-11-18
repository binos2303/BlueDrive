"""Workspace upload lifecycle with real quota accounting and mocked object storage."""
import hashlib
import io
import uuid
from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Membership, QuotaAccount, Workspace, WorkspaceMembership
from files.finalization import finalize_verified_upload
from files.models import File, QuotaReservation, UploadFinalizationJob, UploadSession
from files.storage_adapters.base import MultipartUpload, ObjectStat, StorageAdapter, StorageError, StorageIntegrityError, StorageNotFoundError
from folders.models import Folder


class WorkspaceUploadQuotaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="workspace-quota-owner")
        self.editor = User.objects.create_user(username="workspace-quota-editor")
        self.tenant = self.owner.personal_tenant
        self.space = Workspace.objects.create(tenant=self.tenant, name="Upload checks", slug="upload-checks", created_by=self.owner)
        membership = Membership.objects.create(tenant=self.tenant, user=self.editor, role="member", status="active")
        self.assignment = WorkspaceMembership.objects.create(workspace=self.space, membership=membership, role="editor", status="active")
        self.quota = QuotaAccount.objects.get(workspace=self.space, scope="workspace")
        self.quota.limit_bytes = 100
        self.quota.save(update_fields=["limit_bytes"])
        self.personal = list(QuotaAccount.objects.filter(scope="tenant", tenant__in=[self.tenant, self.editor.personal_tenant]))
        for account in self.personal:
            account.limit_bytes = 0
            account.save(update_fields=["limit_bytes"])
        self.client = APIClient()
        self.client.force_authenticate(self.editor)
        self.adapter = Mock(spec=StorageAdapter)
        self.adapter.create_object_key.side_effect = lambda scope: f"{scope}/{uuid.uuid4().hex}"
        self.adapter.initiate_multipart.return_value = MultipartUpload("fixture-provider-upload")
        self.adapter.put_object.return_value = ObjectStat(size_bytes=0, version_id="fixture-put")
        self.adapter.publish_verified_object.return_value = ObjectStat(size_bytes=0, version_id="fixture-copy")
        for module in ["files.upload_api", "files.finalization", "files.management.commands.finalize_uploads"]:
            self.enterContext(patch(f"{module}.get_storage_adapter", return_value=self.adapter))
        self.payload = b"workspace audit sample\n"

    def create(self, *, size=None, key="", folder=None):
        data = {"name": "workspace.txt", "size_bytes": len(self.payload) if size is None else size, "sha256": hashlib.sha256(self.payload).hexdigest()}
        if folder:
            data["folder_id"] = folder.pk
        return self.client.post("/files/api/uploads/", data, format="json", HTTP_X_WORKSPACE_ID=str(self.space.pk), HTTP_IDEMPOTENCY_KEY=key)

    def assert_usage(self, used, reserved):
        self.quota.refresh_from_db()
        self.assertEqual((self.quota.used_bytes, self.quota.reserved_bytes), (used, reserved))
        for account in self.personal:
            account.refresh_from_db()
            self.assertEqual((account.used_bytes, account.reserved_bytes), (0, 0), "Workspace must not consume either user's private quota")

    def test_cross_tenant_editor_reserves_workspace_only_and_replay_is_idempotent(self):
        first = self.create(size=60, key="workspace-upload")
        self.assertEqual(first.status_code, 201, first.data)
        second = self.create(size=60, key="workspace-upload")
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["upload_id"], second.data["upload_id"])
        upload = UploadSession.objects.get(pk=first.data["upload_id"])
        self.assertEqual((upload.tenant_id, upload.workspace_id), (self.tenant.pk, self.space.pk))
        self.assertEqual(upload.initiated_by_id, self.editor.pk)
        self.assertEqual(QuotaReservation.objects.get(upload_session=upload).quota_account_id, self.quota.pk)
        self.adapter.initiate_multipart.assert_called_once()
        self.assert_usage(0, 60)

    def test_same_idempotency_key_with_different_payload_does_not_reserve_again(self):
        self.assertEqual(self.create(size=60, key="same-key").status_code, 201)
        self.assertEqual(self.create(size=61, key="same-key").status_code, 409)
        self.assertEqual(QuotaReservation.objects.count(), 1)
        self.adapter.initiate_multipart.assert_called_once()
        self.assert_usage(0, 60)

    def test_quota_rejection_does_not_allocate_another_multipart_or_reservation(self):
        self.assertEqual(self.create(size=60).status_code, 201)
        rejected = self.create(size=41)
        self.assertEqual(rejected.status_code, 413)
        self.assertEqual(rejected.data["failure_code"], "quota_exceeded")
        self.assertEqual(QuotaReservation.objects.count(), 1)
        self.adapter.initiate_multipart.assert_called_once()
        self.assert_usage(0, 60)

    def test_abort_releases_workspace_quota_once(self):
        response = self.create(size=60)
        self.assertEqual(response.status_code, 201)
        url = f'/files/api/uploads/{response.data["upload_id"]}/abort/'
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(QuotaReservation.objects.get().state, "released")
        self.assert_usage(0, 0)

    def test_abort_recovers_session_interrupted_before_quota_reservation(self):
        upload = UploadSession.objects.create(tenant=self.tenant,workspace=self.space,initiated_by=self.editor,
            client_name='interrupted.txt',expected_size_bytes=10,expected_sha256='a'*64,
            object_key='staging/'+uuid.uuid4().hex,expires_at=timezone.now()+timedelta(hours=1))
        self.assertFalse(QuotaReservation.objects.filter(upload_session=upload).exists())
        response = self.client.post(f'/files/api/uploads/{upload.pk}/abort/')
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data['state'],'canceled')
        self.assert_usage(0,0)

    def test_storage_setup_failure_returns_reserved_workspace_capacity(self):
        self.adapter.initiate_multipart.side_effect = StorageError("fixture setup failure")
        with self.assertLogs("files.upload_api", level="ERROR"):
            response = self.create(size=60)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["failure_code"], "storage_setup_failed")
        self.assertFalse(QuotaReservation.objects.exists(), 'Atomic initialization rolls back the reservation on setup failure')
        self.assert_usage(0, 0)

    def test_missing_workspace_quota_fails_closed(self):
        self.quota.delete()
        response = self.create()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["failure_code"], "quota_unconfigured")
        self.adapter.initiate_multipart.assert_not_called()
        self.assertFalse(QuotaReservation.objects.exists())

    def test_viewer_cannot_reserve_any_quota(self):
        self.assignment.role = "viewer"
        self.assignment.save(update_fields=["role"])
        self.assertEqual(self.create().status_code, 404)
        self.adapter.initiate_multipart.assert_not_called()
        self.assertFalse(UploadSession.objects.exists())
        self.assert_usage(0, 0)

    def test_downgraded_editor_cannot_complete_but_can_release_its_reservation(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        url = f'/files/api/uploads/{response.data["upload_id"]}'
        self.assignment.role = "viewer"
        self.assignment.save(update_fields=["role"])
        self.assertEqual(self.client.post(f"{url}/parts/authorizations/", {"part_numbers": [1]}, format="json").status_code, 404)
        self.assertEqual(self.client.post(f"{url}/complete/", {"parts": [{"part_number": 1, "etag": "fixture"}]}, format="json").status_code, 404)
        self.assertEqual(self.client.post(f"{url}/abort/").status_code, 200)
        self.assert_usage(0, 0)

    def test_expired_upload_returns_reserved_capacity(self):
        response = self.create(size=60)
        upload_id = response.data["upload_id"]
        UploadSession.objects.filter(pk=upload_id).update(expires_at=timezone.now() - timedelta(seconds=1))
        result = self.client.get(f"/files/api/uploads/{upload_id}/")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["state"], "expired")
        self.assertTrue(result.data['cleanup_pending'])
        self.assertEqual(QuotaReservation.objects.get().state, 'reserved')
        self.assert_usage(0,60)
        with patch('files.management.commands.cleanup_uploads.get_storage_adapter',return_value=self.adapter):
            call_command('cleanup_uploads',stdout=io.StringIO())
        self.assertEqual(QuotaReservation.objects.get().state, "released")
        self.assert_usage(0, 0)

    def test_abort_on_past_deadline_keeps_expired_state(self):
        response = self.create(size=60)
        upload_id = response.data["upload_id"]
        UploadSession.objects.filter(pk=upload_id).update(expires_at=timezone.now() - timedelta(seconds=1))
        url = f"/files/api/uploads/{upload_id}/abort/"
        self.assertEqual(self.client.post(url).data["state"], "expired")
        self.assertEqual(self.client.post(url).data["state"], "expired")
        self.assertEqual(UploadSession.objects.get(pk=upload_id).failure_code, "expired")
        self.assertEqual(QuotaReservation.objects.get(upload_session_id=upload_id).state, "released")
        self.assert_usage(0, 0)

    def test_folder_upload_finalization_consumes_workspace_quota_only_once(self):
        folder = Folder.objects.create(tenant=self.tenant, workspace=self.space, owner=self.owner, folder_name="Destination")
        response = self.create(folder=folder)
        self.assertEqual(response.status_code, 201, response.data)
        upload_id = response.data["upload_id"]
        result = self.client.post(f"/files/api/uploads/{upload_id}/complete/", {"parts": [{"part_number": 1, "etag": "fixture"}]}, format="json")
        self.assertEqual(result.status_code, 202)
        self.assertEqual(UploadFinalizationJob.objects.get().state, "pending")
        upload = UploadSession.objects.get(pk=upload_id)
        digest = hashlib.sha256(self.payload).hexdigest()
        published = finalize_verified_upload(upload, io.BytesIO(self.payload), self.editor, verified_sha256=digest)
        upload.refresh_from_db()
        self.assertEqual(upload.state, "available")
        file = File.objects.get(pk=published["file_id"])
        self.assertEqual((file.workspace_id, file.folder_id), (self.space.pk, folder.pk))
        finalize_verified_upload(upload, io.BytesIO(self.payload), self.editor, verified_sha256=digest)
        self.assertEqual(File.objects.count(), 1)
        self.assert_usage(len(self.payload), 0)

    def test_finalizer_failure_releases_workspace_reservation(self):
        response = self.create()
        upload_id = response.data["upload_id"]
        self.client.post(f"/files/api/uploads/{upload_id}/complete/", {"parts": [{"part_number": 1, "etag": "fixture"}]}, format="json")
        self.adapter.complete_multipart.side_effect = StorageIntegrityError("fixture integrity failure")
        self.adapter.stat_object.side_effect = StorageNotFoundError("fixture has no completed object")
        with self.assertLogs("files.management.commands.finalize_uploads", level="WARNING"):
            call_command("finalize_uploads", stdout=io.StringIO())
        self.assertEqual(UploadSession.objects.get(pk=upload_id).state, "failed")
        self.assertEqual(UploadFinalizationJob.objects.get().state, "failed")
        self.assertEqual(QuotaReservation.objects.get().state, "released")
        self.assert_usage(0, 0)
