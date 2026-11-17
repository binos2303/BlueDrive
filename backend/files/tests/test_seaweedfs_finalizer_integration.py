"""Upload API → SeaweedFS thật → worker hiện có → download và quota."""
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Membership, QuotaAccount, Workspace, WorkspaceMembership
from accounts.access import get_default_workspace
from files.models import File, FileVersion, QuotaReservation, StorageLocation, UploadFinalizationJob, UploadSession
from files.storage_adapters import get_storage_adapter
from files.storage_adapters.base import StorageRetryableError
from files.tests import test_seaweedfs_integration as s3_gate
from files.views import _decrypt_file
from folders.models import Folder
from infrastructure.connection_probes import begin_probe, cleanup_probe, complete_probe, runtime_authorizations
from infrastructure.connections import activate_binding, register_connection, verify_read_only
from logs.models import ActivityLog
from securedrive.test_environment import OS_VARIABLES
from sharing.models import Share


@unittest.skipUnless(os.getenv("SEAWEEDFS_INTEGRATION") == "1", "BLOCKED: cần SeaweedFS thật; không mock worker.")
class SeaweedFSFinalizerIntegrationTests(TransactionTestCase):
    # Không bọc toàn bài trong transaction: gate retry phải quan sát commit thật trước/sau S3.
    serialized_rollback = True

    def setUp(self):
        s3_gate.SeaweedFSIntegrationTests.setUpClass()
        self.addCleanup(s3_gate.SeaweedFSIntegrationTests.tearDownClass)
        self.enterContext(self.settings(
            DEBUG=True, SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED=False,
            SECUREDRIVE_STORAGE_ENDPOINT_URL=os.environ["SEAWEED_S3_ENDPOINT"],
            SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL=os.environ["SEAWEED_S3_PUBLIC_ENDPOINT"],
            SECUREDRIVE_STORAGE_BUCKET=os.environ["SEAWEED_S3_BUCKET"],
            SECUREDRIVE_STORAGE_ACCESS_KEY_ID=os.environ["SEAWEED_S3_ACCESS_KEY"],
            SECUREDRIVE_STORAGE_SECRET_ACCESS_KEY=os.environ["SEAWEED_S3_SECRET_KEY"],
            SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=False,
            SECUREDRIVE_STORAGE_SSE="", SECUREDRIVE_UPLOAD_SCANNER=""))
        self.user = get_user_model().objects.create_user(username="seaweed-gate-" + uuid.uuid4().hex)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.storage = get_storage_adapter()
        self.addCleanup(self.storage._client.close)

    def upload(self, payload, expected_sha256, *, run_worker=True, replay=False):
        data = {"name": "seaweed-gate.txt", "size_bytes": len(payload), "sha256": expected_sha256}
        request_key = uuid.uuid4().hex
        response = self.client.post("/files/api/uploads/", data, format="json", HTTP_IDEMPOTENCY_KEY=request_key)
        self.assertEqual(response.status_code, 201)
        upload_id = response.data["upload_id"]
        session = UploadSession.objects.get(pk=upload_id)
        self.addCleanup(self.storage.delete_object, session.object_key)
        if replay:
            repeated = self.client.post("/files/api/uploads/", data, format="json", HTTP_IDEMPOTENCY_KEY=request_key)
            self.assertEqual(repeated.status_code, 200)
            self.assertEqual(repeated.data["upload_id"], upload_id)
            self.assertEqual(UploadSession.objects.filter(initiated_by=self.user).count(), 1)
        return self.finish_upload(session, payload, run_worker=run_worker)

    def finish_upload(self, session, payload, *, run_worker=True):
        upload_id = str(session.pk)
        self.addCleanup(self.storage.delete_object, session.object_key)
        parts = []
        if payload:
            self.addCleanup(self.storage.abort_multipart, session.object_key, session.provider_upload_id)
            authorization = self.client.post(f"/files/api/uploads/{upload_id}/parts/1/authorization/")
            self.assertEqual(authorization.status_code, 200)
            status, headers, _ = s3_gate.http(authorization.data["url"], method="PUT", body=payload, headers=authorization.data["headers"])
            self.assertEqual(status, 200)
            parts = [{"part_number": 1, "etag": headers["ETag"]}]
            resumed = self.client.get(f"/files/api/uploads/{upload_id}/parts/")
            self.assertEqual(resumed.status_code, 200)
            self.assertEqual(resumed.data["parts"][0]["etag"], parts[0]["etag"])
        completed = self.client.post(f"/files/api/uploads/{upload_id}/complete/", {"parts": parts}, format="json")
        self.assertEqual(completed.status_code, 202)
        if run_worker:
            call_command("finalize_uploads", stdout=io.StringIO())
        session.refresh_from_db()
        for key in (session.final_object_key, session.object_key):
            if key:
                self.addCleanup(self.storage.delete_object, key)
        return session

    def qualified_platform(self):
        profile_id = "seaweed-p4-fixture"
        profiles = {profile_id: {
            "scope": "platform", "provider": "s3", "lab": True,
            "endpoint_url": os.environ["SEAWEED_S3_ENDPOINT"],
            "public_endpoint_url": os.environ["SEAWEED_S3_PUBLIC_ENDPOINT"],
            "bucket": os.environ["SEAWEED_S3_BUCKET"], "allowed_networks": ["127.0.0.1/32"],
            "access_key_env": "SEAWEED_S3_ACCESS_KEY", "secret_key_env": "SEAWEED_S3_SECRET_KEY",
            "server_side_encryption": "",
        }}
        self.enterContext(self.settings(
            SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True,
            SECUREDRIVE_STORAGE_RUNTIME_PROBES_ENABLED=True,
            SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=True,
            SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED=True,
            SECUREDRIVE_STORAGE_CONNECTION_PROFILES=profiles))
        actor = get_user_model().objects.create_superuser(username="seaweed-operator-" + uuid.uuid4().hex)
        connection, created = register_connection(actor, None, {
            "profile_id": profile_id, "display_name": "Isolated SeaweedFS fixture",
            "slug": "p4-" + uuid.uuid4().hex, "reason": "Qualify isolated provider fixture",
        }, uuid.uuid4().hex)
        self.assertTrue(created)
        origin = os.environ["FRONTEND_ORIGINS"].split(",")[0]
        connection, _ = verify_read_only(connection, actor, "Inspect isolated provider fixture", origin)
        self.assertEqual(connection.state, "read_verified")
        probe, _ = begin_probe(connection, actor, "Transfer isolated provider fixture", origin, mode="runtime")
        self.addCleanup(cleanup_probe, probe, actor)
        ticket = {"mode": "runtime", "origin": origin, **runtime_authorizations(probe)}
        script = Path(__file__).resolve().parents[3] / "infra/seaweedfs/browser-smoke.mjs"
        # Browser chỉ nhận URL challenge qua stdin; home/cache tạm và không nhận credential DB/S3.
        with tempfile.TemporaryDirectory(prefix="seaweed-browser-") as directory:
            home = Path(directory)
            browser_environment = {key: value for key, value in os.environ.items() if key.upper() in OS_VARIABLES}
            browser_environment.update(HOME=directory, USERPROFILE=directory,
                                       XDG_CONFIG_HOME=str(home / ".config"), XDG_CACHE_HOME=str(home / ".cache"))
            if os.name == "nt":
                for key, relative in (("LOCALAPPDATA", "AppData/Local"), ("APPDATA", "AppData/Roaming")):
                    folder = home / relative
                    folder.mkdir(parents=True)
                    browser_environment[key] = str(folder)
                drive = Path(os.environ["SYSTEMROOT"]).anchor
                browser_environment.update(PROGRAMFILES=str(Path(drive) / "Program Files"),
                                           **{"PROGRAMFILES(X86)": str(Path(drive) / "Program Files (x86)")})
            browser = subprocess.run(["node", str(script)], input=json.dumps(ticket), encoding="utf-8",
                                     env=browser_environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        self.assertEqual(browser.returncode, 0, "Chrome fixture gate failed; URLs/output withheld.")
        receipt = json.loads(browser.stdout)
        probe = complete_probe(probe, actor, receipt["sha256"],
                               put_digest=receipt["put_sha256"], put_etag=receipt["put_etag"])
        self.assertEqual(probe.state, "succeeded")
        connection.refresh_from_db()
        self.assertEqual(connection.state, "ready")
        binding, replayed = activate_binding(connection, actor, None, 0, "Bind isolated provider fixture")
        self.assertFalse(replayed)
        self.assertEqual(binding.connection_id, connection.pk)
        self.storage = get_storage_adapter(connection=connection)
        self.addCleanup(self.storage._client.close)
        return connection

    def login_fixture(self):
        password = secrets.token_urlsafe(36)
        self.user.email = uuid.uuid4().hex + "@example.test"
        self.user.set_password(password)
        self.user.save(update_fields=["email", "password"])
        self.client = APIClient(enforce_csrf_checks=True)
        credentials = {"email": self.user.email, "password": password}
        self.assertEqual(self.client.post(reverse("api-login"), credentials, format="json").status_code, 403)
        csrf = self.client.get(reverse("api-csrf"))
        self.assertEqual(csrf.status_code, 200)
        response = self.client.post(reverse("api-login"), credentials, format="json", HTTP_X_CSRFTOKEN=csrf.data["csrfToken"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse("api-current-account")).status_code, 200)
        self.assertEqual(self.client.post("/files/api/uploads/", {}, format="json").status_code, 403)
        # Login xoay CSRF token; lấy lại bootstrap thay vì tái dùng token trước login.
        self.client.credentials(HTTP_X_CSRFTOKEN=self.client.get(reverse("api-csrf")).data["csrfToken"])

    def assert_publication_once(self, session, payload, connection):
        session.refresh_from_db()
        self.assertEqual(session.state, UploadSession.State.AVAILABLE)
        self.assertEqual(session.storage_connection_id, connection.pk)
        self.assertEqual(session.endpoint_config_version, connection.revision)
        self.assertEqual(session.tenant_id, self.user.personal_tenant.pk)
        self.assertEqual(session.workspace.tenant_id, session.tenant_id)
        self.assertEqual(session.workspace_id, get_default_workspace(self.user.personal_tenant).pk)
        self.assertEqual(session.file.workspace_id, session.workspace_id)
        version = FileVersion.objects.get(file_id=session.file_id)
        location = StorageLocation.objects.get(file_version=version)
        self.assertEqual(location.storage_connection_id, connection.pk)
        self.assertEqual(location.tenant_id, session.tenant_id)
        self.assertEqual(location.object_ref, session.final_object_key)
        self.assertTrue(location.provider_version_id and location.provider_version_id != "null")
        self.assertEqual(version.sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(location.checksum, version.sha256)
        self.assertEqual(File.objects.filter(owner=self.user).count(), 1)
        self.assertEqual(ActivityLog.objects.filter(action=ActivityLog.Action.UPLOAD,
                                                  metadata__upload_id=str(session.pk)).count(), 1)
        self.assertEqual(set(QuotaReservation.objects.filter(upload_session=session).values_list("state", flat=True)),
                         {QuotaReservation.State.CONSUMED})
        quota = QuotaAccount.objects.get(tenant=session.tenant, scope="tenant")
        self.assertEqual((quota.used_bytes, quota.reserved_bytes), (len(payload), 0))
        return location

    def test_pinned_upload_direct_download_and_replay_keep_quota_once(self):
        connection = self.qualified_platform()
        self.login_fixture()
        payload = b"Pinned SeaweedFS upload and direct download\n"
        session = self.upload(payload, hashlib.sha256(payload).hexdigest(), replay=True)
        call_command("finalize_uploads", stdout=io.StringIO())
        location = self.assert_publication_once(session, payload, connection)
        endpoint = reverse("file_download_url", args=[session.file_id])
        response = self.client.get(endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["mode"], "presigned")
        self.assertEqual(parse_qs(urlsplit(response.data["url"]).query)["versionId"], [location.provider_version_id])
        status, _, downloaded = s3_gate.http(response.data["url"])
        self.assertEqual((status, downloaded), (200, payload))
        identity = (location.pk, location.object_ref, location.provider_version_id)
        folder = Folder.objects.create(tenant=session.tenant, workspace=session.workspace, owner=self.user,
                                       folder_name="Lifecycle fixture")
        recipient = get_user_model().objects.create_user(username="seaweed-recipient-" + uuid.uuid4().hex,
                                                         email=uuid.uuid4().hex + "@example.test")
        selected = {"file_ids": [session.file_id], "folder_ids": []}
        for operation, body in (
            ("rename", {"kind": "file", "id": session.file_id, "name": "renamed-fixture.txt"}),
            ("move", {**selected, "destination_folder_id": folder.pk}),
            ("share", {**selected, "email": recipient.email, "permission": "viewer"}),
            ("trash", selected),
            ("restore", selected),
        ):
            with self.subTest(operation=operation):
                changed = self.client.post(reverse(f"drive_items_{operation}_api"), body, format="json")
                self.assertEqual(changed.status_code, 200)
                session.file.refresh_from_db()
                location.refresh_from_db()
                self.assertEqual((location.pk, location.object_ref, location.provider_version_id), identity)
                with self.storage.open_object(location.object_ref, version_id=location.provider_version_id) as stored:
                    self.assertEqual(stored.read(), payload)
                if operation == "rename":
                    self.assertEqual(session.file.file_name, "renamed-fixture.txt")
                elif operation == "move":
                    self.assertEqual(session.file.folder_id, folder.pk)
                elif operation == "share":
                    self.assertTrue(Share.objects.filter(file=session.file, receiver=recipient, permission="viewer").exists())
                    receiver = APIClient()
                    receiver.force_login(recipient)
                    shared = receiver.get(endpoint)
                    self.assertEqual(shared.status_code, 200)
                    self.assertEqual(s3_gate.http(shared.data["url"])[2], payload)
                elif operation == "trash":
                    self.assertIsNotNone(session.file.deleted_at)
                    self.assertEqual(self.client.get(endpoint).status_code, 404)
                elif operation == "restore":
                    self.assertIsNone(session.file.deleted_at)
                    self.assertEqual(self.client.get(endpoint).status_code, 200)
        self.assert_publication_once(session, payload, connection)
        Membership.objects.filter(user=self.user, tenant=session.tenant).update(status=Membership.Status.REVOKED)
        self.assertEqual(self.client.get(endpoint).status_code, 403)
        # URL đã phát hành còn hiệu lực đến TTL; thu hồi quyền chỉ chặn lần cấp mới.
        self.assertEqual(s3_gate.http(response.data["url"])[0], 200)
        self.assertEqual(self.client.post(reverse("api-logout")).status_code, 204)
        self.assertEqual(self.client.get(reverse("api-current-account")).status_code, 403)

    def test_real_publish_recovers_after_metadata_commit_failure(self):
        connection = self.qualified_platform()
        payload = b"Published bytes survive one metadata rollback\n"
        session = self.upload(payload, hashlib.sha256(payload).hexdigest(), run_worker=False)
        # Chỉ fault-inject ghi metadata; S3 PUT/COPY/GET vẫn là provider thật.
        with patch("files.finalization.File.objects.create", side_effect=IntegrityError("fixture metadata rollback")):
            call_command("finalize_uploads", stdout=io.StringIO())
        session.refresh_from_db()
        self.addCleanup(self.storage.delete_object, session.final_object_key)
        self.assertEqual(session.state, UploadSession.State.VERIFYING)
        self.assertIsNone(session.file_id)
        self.assertFalse(File.objects.filter(owner=self.user).exists())
        self.assertEqual(UploadFinalizationJob.objects.get(upload_session=session).state, "pending")
        final_key = session.final_object_key
        self.assertTrue(final_key)
        with self.storage.open_object(final_key) as body:
            self.assertEqual(body.read(), payload)
        quota = QuotaAccount.objects.get(tenant=session.tenant, scope="tenant")
        self.assertEqual((quota.used_bytes, quota.reserved_bytes), (0, len(payload)))
        self.assertEqual(set(QuotaReservation.objects.filter(upload_session=session).values_list("state", flat=True)),
                         {QuotaReservation.State.RESERVED})
        # Timeout mô phỏng tại biên adapter; retry tiếp theo vẫn đọc/copy bytes S3 thật.
        with patch("files.storage_adapters.s3_compatible.S3CompatibleStorageAdapter.download_to",
                   side_effect=StorageRetryableError("fixture read timeout")):
            call_command("finalize_uploads", stdout=io.StringIO())
        session.refresh_from_db()
        job = UploadFinalizationJob.objects.get(upload_session=session)
        self.assertEqual((session.state, job.state, job.attempts), ("verifying", "pending", 2))
        quota.refresh_from_db()
        self.assertEqual((quota.used_bytes, quota.reserved_bytes), (0, len(payload)))
        self.assertEqual(set(QuotaReservation.objects.filter(upload_session=session).values_list("state", flat=True)),
                         {QuotaReservation.State.RESERVED})
        call_command("finalize_uploads", stdout=io.StringIO())
        location = self.assert_publication_once(session, payload, connection)
        self.assertEqual(session.final_object_key, final_key)
        job = UploadFinalizationJob.objects.get(upload_session=session)
        self.assertEqual((job.state, job.attempts), ("done", 3))
        call_command("finalize_uploads", stdout=io.StringIO())
        self.assert_publication_once(session, payload, connection)
        self.login_fixture()
        selected = {"file_ids": [session.file_id], "folder_ids": []}
        self.assertEqual(self.client.post(reverse("drive_items_trash_api"), selected, format="json").status_code, 200)
        file_id, version_id = session.file_id, location.file_version_id
        # Lỗi xóa phải giữ metadata và quota để thử lại; không báo thành công giả.
        with patch("files.storage_adapters.s3_compatible.S3CompatibleStorageAdapter.delete_object",
                   side_effect=StorageRetryableError("fixture delete timeout")):
            failed = self.client.post(reverse("drive_items_delete_api"), selected, format="json")
        self.assertEqual(failed.status_code, 503)
        location.refresh_from_db()
        self.assertEqual(location.state, StorageLocation.State.ERROR)
        self.assertTrue(File.objects.filter(pk=file_id).exists())
        self.assertTrue(FileVersion.objects.filter(pk=version_id).exists())
        quota.refresh_from_db()
        self.assertEqual((quota.used_bytes, quota.reserved_bytes), (len(payload), 0))
        with self.storage.open_object(final_key, version_id=location.provider_version_id) as stored:
            self.assertEqual(stored.read(), payload)
        deleted = self.client.post(reverse("drive_items_delete_api"), selected, format="json")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(File.objects.filter(pk=file_id).exists())
        self.assertFalse(FileVersion.objects.filter(pk=version_id).exists())
        self.assertFalse(StorageLocation.objects.filter(pk=location.pk).exists())
        session.refresh_from_db()
        self.assertIsNone(session.file_id)
        quota.refresh_from_db()
        self.assertEqual((quota.used_bytes, quota.reserved_bytes), (0, 0))
        versions = self.storage._client.list_object_versions(Bucket=connection.bucket, Prefix=final_key)
        self.assertFalse([entry for entry in versions.get("Versions", []) + versions.get("DeleteMarkers", [])
                          if entry["Key"] == final_key])

    def test_concurrent_workspace_admission_keeps_its_budget_and_finalizes_once(self):
        connection = self.qualified_platform()
        workspace = Workspace.objects.create(tenant=self.user.personal_tenant, name="Concurrent fixture",
                                             slug="concurrent-fixture", created_by=self.user)
        editor = get_user_model().objects.create_user(username="seaweed-editor-" + uuid.uuid4().hex)
        membership = Membership.objects.create(tenant=workspace.tenant, user=editor, role="member")
        WorkspaceMembership.objects.create(workspace=workspace, membership=membership, role="editor")
        quota = QuotaAccount.objects.get(workspace=workspace, scope="workspace")
        quota.limit_bytes = 100
        quota.save(update_fields=["limit_bytes"])
        personal_quotas = list(QuotaAccount.objects.filter(scope="tenant", tenant__in=[workspace.tenant, editor.personal_tenant]))
        for personal in personal_quotas:
            personal.limit_bytes = 0
            personal.save(update_fields=["limit_bytes"])

        def cleanup_uploads():
            for upload in UploadSession.objects.filter(workspace=workspace):
                if upload.provider_upload_id:
                    self.storage.abort_multipart(upload.object_key, upload.provider_upload_id)
                for key in {upload.object_key, upload.final_object_key} - {""}:
                    self.storage.delete_object(key)

        self.addCleanup(cleanup_uploads)
        payload = b"w" * 60
        barrier = Barrier(2)

        def attempt(index):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=editor.pk))
                barrier.wait(timeout=10)
                response = client.post("/files/api/uploads/", {
                    "name": f"concurrent-{index}.txt", "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }, format="json", HTTP_X_WORKSPACE_ID=str(workspace.pk), HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex)
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, range(2)))
        self.assertCountEqual(results, [201, 413])
        quota.refresh_from_db()
        self.assertEqual((quota.used_bytes, quota.reserved_bytes), (0, len(payload)))
        winner = UploadSession.objects.get(workspace=workspace, state=UploadSession.State.UPLOADING)
        self.assertEqual((winner.storage_connection_id, winner.workspace_id, winner.tenant_id),
                         (connection.pk, workspace.pk, workspace.tenant_id))
        self.client = APIClient()
        self.client.force_authenticate(editor)
        self.client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.pk))
        winner = self.finish_upload(winner, payload)
        self.assertEqual(winner.state, UploadSession.State.AVAILABLE)
        self.assertEqual(File.objects.filter(workspace=workspace).count(), 1)
        location = StorageLocation.objects.get(file_version__file=winner.file)
        self.assertEqual(location.storage_connection_id, connection.pk)
        with self.storage.open_object(location.object_ref, version_id=location.provider_version_id) as stored:
            self.assertEqual(stored.read(), payload)
        quota.refresh_from_db()
        self.assertEqual((quota.used_bytes, quota.reserved_bytes), (len(payload), 0))
        self.assertEqual(QuotaReservation.objects.filter(upload_session=winner, state="consumed").count(), 1)
        self.assertEqual(ActivityLog.objects.filter(action=ActivityLog.Action.UPLOAD,
                                                  metadata__upload_id=str(winner.pk)).count(), 1)
        for personal in personal_quotas:
            personal.refresh_from_db()
            self.assertEqual((personal.used_bytes, personal.reserved_bytes), (0, 0))

    def test_existing_worker_publishes_and_downloads_exact_bytes_and_consumes_quota(self):
        for payload in (b"SeaweedFS finalization gate\n", b""):
            with self.subTest(empty=not payload):
                session = self.upload(payload, hashlib.sha256(payload).hexdigest())
                self.assertEqual(session.state, UploadSession.State.AVAILABLE)
                location = StorageLocation.objects.get(file_version__file_id=session.file_id)
                self.assertEqual(location.storage_config.provider, "s3")
                self.assertEqual(_decrypt_file(session.file), payload)
                self.assertEqual(UploadFinalizationJob.objects.get(upload_session=session).state, "done")
        quota = QuotaAccount.objects.get(tenant=self.user.personal_tenant, scope="tenant")
        self.assertEqual(quota.reserved_bytes, 0)
        self.assertEqual(quota.used_bytes, len(b"SeaweedFS finalization gate\n"))

    def test_full_file_hash_mismatch_does_not_publish_and_releases_quota(self):
        session = self.upload(b"tampered contents\n", "0" * 64)
        self.assertEqual(session.state, UploadSession.State.FAILED)
        self.assertIsNone(session.file_id)
        self.assertFalse(File.objects.filter(owner=self.user).exists())
        quota = QuotaAccount.objects.get(tenant=self.user.personal_tenant, scope="tenant")
        self.assertEqual((quota.used_bytes, quota.reserved_bytes), (0, 0))
