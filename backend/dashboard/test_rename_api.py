"""Sprint 2.1 regression tests: permission and consistency for JSON Rename."""
import json
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.access import get_default_workspace
from accounts.models import Membership, WorkspaceMembership
from accounts.services import get_personal_tenant
from files.models import File
from folders.models import Folder
from logs.models import ActivityLog

User = get_user_model()


class DriveRenameApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="rename-owner", email="owner@example.test", password="secret123!",
        )
        self.other = User.objects.create_user(
            username="rename-other", email="other@example.test", password="secret123!",
        )
        self.tenant = get_personal_tenant(self.owner)
        self.workspace = get_default_workspace(self.tenant)
        self.folder = Folder.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            folder_name="Documents",
        )
        self.file = File.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            folder=self.folder, file_name="report.txt", mime_type="text/plain", file_size=7,
        )
        self.client.force_login(self.owner)
        self.url = reverse("drive_items_rename_api")

    def rename(self, kind, item_id, name, **extra_headers):
        return self.client.post(
            self.url, data=json.dumps({"kind": kind, "id": item_id, "name": name}),
            content_type="application/json", **extra_headers,
        )

    def test_file_rename_preserves_file_storage_metadata_and_audits_once(self):
        original_hash = self.file.hash_sha256
        original_path = self.file.file_path.name
        res = self.rename("file", self.file.pk, "final.txt")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()["changed"])
        self.file.refresh_from_db()
        self.assertEqual(self.file.file_name, "final.txt")
        self.assertEqual(self.file.hash_sha256, original_hash)
        self.assertEqual(self.file.file_path.name, original_path)
        self.assertEqual(ActivityLog.objects.filter(
            user=self.owner, action=ActivityLog.Action.RENAME,
        ).count(), 1)
        repeat = self.rename("file", self.file.pk, "final.txt")
        self.assertEqual(repeat.status_code, 200)
        self.assertFalse(repeat.json()["changed"])
        self.assertEqual(ActivityLog.objects.filter(
            user=self.owner, action=ActivityLog.Action.RENAME,
        ).count(), 1)

    def test_folder_rename_updates_only_its_metadata(self):
        result = self.rename("folder", self.folder.pk, "Renamed Documents")
        self.assertEqual(result.status_code, 200, result.content)
        self.folder.refresh_from_db()
        self.assertEqual(self.folder.folder_name, "Renamed Documents")
        self.file.refresh_from_db()
        self.assertEqual(self.file.folder_id, self.folder.pk)

    def test_invalid_names_extension_and_request_are_rejected(self):
        for kind, item_id, name in (
            ("file", self.file.pk, "changed.pdf"),
            ("file", self.file.pk, "../bad.txt"),
            ("file", self.file.pk, ""),
            ("folder", self.folder.pk, "  "),
            ("folder", self.folder.pk, "../unsafe"),
        ):
            with self.subTest(kind=kind, name=name):
                result = self.rename(kind, item_id, name)
                self.assertEqual(result.status_code, 400, result.content)
        result = self.client.post(self.url, json.dumps({"kind": "file", "id": True, "name": "ok.txt"}), content_type="application/json")
        self.assertEqual(result.status_code, 400)

    def test_duplicates_are_workspace_wide_not_scoped_to_same_owner(self):
        # Ensure the second user belongs to the tenant before owning its files.
        Membership.objects.get_or_create(
            tenant=self.tenant,
            user=self.other,
            defaults={
                "role": Membership.Role.MEMBER,
                "status": Membership.Status.ACTIVE,
            },
        )

        # Another member owns a file with the target name.
        File.objects.create(
            tenant=self.tenant,
            workspace=self.workspace,
            owner=self.other,
            folder=self.folder,
            file_name="existing.txt",
            mime_type="text/plain",
        )

        # File names must be unique within the same workspace and folder,
        # regardless of which user owns the file.
        response = self.rename("file", self.file.pk, "Existing.txt")
        self.assertEqual(response.status_code, 409, response.content)

        # Another member owns a folder with the target name.
        Folder.objects.create(
            tenant=self.tenant,
            workspace=self.workspace,
            owner=self.other,
            folder_name="Existing Folder",
        )

        # Folder names must also be unique within the same workspace and parent.
        response = self.rename("folder", self.folder.pk, "existing folder")
        self.assertEqual(response.status_code, 409, response.content)
    def test_cross_tenant_resource_not_found(self):
        self.client.force_login(self.other)
        self.assertEqual(self.rename("file", self.file.pk, "stolen.txt").status_code, 404)
        self.assertEqual(self.rename("folder", self.folder.pk, "stolen").status_code, 404)

    def test_workspace_viewer_cannot_rename_even_with_explicit_selector(self):
        membership = Membership.objects.create(
            tenant=self.tenant, user=self.other,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=membership,
            role=WorkspaceMembership.Role.VIEWER, status=WorkspaceMembership.Status.ACTIVE,
        )
        self.client.force_login(self.other)
        headers = {"HTTP_X_WORKSPACE_ID": str(self.workspace.pk)}
        self.assertEqual(self.rename("file", self.file.pk, "hacked.txt", **headers).status_code, 403)
        self.assertEqual(self.rename("folder", self.folder.pk, "hacked", **headers).status_code, 403)
        self.file.refresh_from_db()
        self.assertEqual(self.file.file_name, "report.txt")

    def test_workspace_editor_can_rename_existing_member_file(self):
        membership = Membership.objects.create(
            tenant=self.tenant, user=self.other,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=membership,
            role=WorkspaceMembership.Role.EDITOR, status=WorkspaceMembership.Status.ACTIVE,
        )
        self.client.force_login(self.other)
        response = self.rename(
            "file", self.file.pk, "edited.txt",
            HTTP_X_WORKSPACE_ID=str(self.workspace.pk),
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_csrf_is_required_for_session_mutation(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        payload = json.dumps({"kind": "file", "id": self.file.pk, "name": "secure.txt"})
        rejected = client.post(self.url, payload, content_type="application/json")
        self.assertEqual(rejected.status_code, 403)
        csrf = client.get(reverse("api-csrf"))
        self.assertEqual(csrf.status_code, 200)
        accepted = client.post(self.url, payload, content_type="application/json",
                               HTTP_X_CSRFTOKEN=csrf.json()["csrfToken"])
        self.assertEqual(accepted.status_code, 200, accepted.content)
