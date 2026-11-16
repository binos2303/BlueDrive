import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.db import IntegrityError
from django.db.models.query import QuerySet
from django.utils import timezone

from accounts.models import Membership, Workspace, WorkspaceMembership
from dashboard.views import _unique_copy_folder_name
from files.models import File, FileVersion, StorageConfig, StorageLocation
from files.services import unique_copy_name, unique_upload_name
from folders.models import Folder


class WorkspaceCollaborationTests(TestCase):
    def setUp(self):
        user = get_user_model()
        self.owner = user.objects.create_user(username="collaboration-owner")
        self.editor = user.objects.create_user(username="collaboration-editor")
        self.tenant = self.owner.personal_tenant
        self.workspace = Workspace.objects.create(tenant=self.tenant, name="Collaborative files", slug="collaboration")
        membership = Membership.objects.create(tenant=self.tenant, user=self.editor, role="member")
        self.grant = WorkspaceMembership.objects.create(workspace=self.workspace, membership=membership, role="editor")
        self.root = self.folder("Project", self.owner)
        self.child = self.folder("Drafts", self.editor, self.root)
        self.first = self.file("owner.txt", self.owner, self.root)
        self.second = self.file("editor.txt", self.editor, self.child)
        self.third = self.file("notes.txt", self.owner, self.child)
        self.client.force_login(self.editor)

    def folder(self, name, owner, parent=None):
        return Folder.objects.create(tenant=self.tenant, workspace=self.workspace, owner=owner, folder_name=name, parent=parent)

    def file(self, name, owner, folder=None):
        return File.objects.create(tenant=self.tenant, workspace=self.workspace, owner=owner, file_name=name, folder=folder, file_size=3)

    def post(self, action, **payload):
        return self.client.post(f"/drive/api/items/{action}/", payload, content_type="application/json", HTTP_X_WORKSPACE_ID=str(self.workspace.pk))

    def test_editor_moves_a_colleagues_file_into_a_colleagues_folder(self):
        destination = self.folder("Destination", self.owner)
        response = self.post("move", file_ids=[self.first.pk], destination_folder_id=destination.pk)
        self.assertEqual(response.status_code, 200)
        self.first.refresh_from_db()
        self.assertEqual(self.first.folder_id, destination.pk)
        self.assertEqual(self.first.owner_id, self.owner.pk)

    def test_folder_details_count_every_workspace_creator(self):
        response = self.client.get(f"/drive/folder/{self.root.pk}/details/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["folder_count"], 1)
        self.assertEqual(response.json()["file_count"], 3)

    def test_shared_tree_trash_restore_and_permanent_delete_include_all_creators(self):
        response = self.post("trash", folder_ids=[self.root.pk])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 5)
        self.assertEqual(File.objects.filter(workspace=self.workspace, deleted_at__isnull=False).count(), 3)
        self.assertEqual(Folder.objects.filter(workspace=self.workspace, deleted_at__isnull=False).count(), 2)
        response = self.post("restore", folder_ids=[self.root.pk])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 5)
        self.assertFalse(File.objects.filter(workspace=self.workspace, deleted_at__isnull=False).exists())
        self.post("trash", folder_ids=[self.root.pk])
        response = self.post("delete", folder_ids=[self.root.pk])
        self.assertEqual(response.status_code, 200)
        self.assertFalse(File.objects.filter(workspace=self.workspace).exists())
        self.assertFalse(Folder.objects.filter(workspace=self.workspace).exists())

    def test_legacy_folder_lifecycle_also_includes_colleagues_descendants(self):
        self.client.force_login(self.owner)
        for url, trashed in ((f"/folder/{self.root.pk}/delete/", True), (f"/folder/{self.root.pk}/restore/", False)):
            response = self.client.post(url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(File.objects.filter(workspace=self.workspace, deleted_at__isnull=not trashed).count(), 3)
            self.assertEqual(Folder.objects.filter(workspace=self.workspace, deleted_at__isnull=not trashed).count(), 2)
        self.client.post(f"/folder/{self.root.pk}/delete/")
        self.assertEqual(self.client.post(f"/folder/{self.root.pk}/delete-permanently/").status_code, 302)
        self.assertFalse(File.objects.filter(workspace=self.workspace).exists())
        self.assertFalse(Folder.objects.filter(workspace=self.workspace).exists())

    def test_legacy_bulk_trash_includes_colleagues_descendants(self):
        self.client.force_login(self.owner)
        response = self.client.post("/drive/bulk-action/", {"action": "trash", "folder_ids": [self.root.pk]}, HTTP_X_WORKSPACE_ID=str(self.workspace.pk))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(File.objects.filter(workspace=self.workspace, deleted_at__isnull=False).count(), 3)
        self.assertEqual(Folder.objects.filter(workspace=self.workspace, deleted_at__isnull=False).count(), 2)

    def test_viewer_cannot_mutate_shared_content(self):
        self.grant.role = "viewer"
        self.grant.save(update_fields=["role"])
        for action in ("move", "trash", "duplicate"):
            with self.subTest(action=action):
                self.assertEqual(self.post(action, file_ids=[self.first.pk]).status_code, 403)
        self.first.refresh_from_db()
        self.assertIsNone(self.first.deleted_at)
        self.assertEqual(self.first.folder_id, self.root.pk)

    def test_move_never_accepts_a_destination_in_another_workspace(self):
        other = Workspace.objects.create(tenant=self.tenant, name="Another", slug="another-collaboration")
        destination = Folder.objects.create(tenant=self.tenant, workspace=other, owner=self.owner, folder_name="Private target")
        self.assertEqual(self.post("move", file_ids=[self.first.pk], destination_folder_id=destination.pk).status_code, 404)
        self.first.refresh_from_db()
        self.assertEqual(self.first.folder_id, self.root.pk)

    def test_restore_conflicts_with_other_creators_are_reported_without_partial_restore(self):
        self.post("trash", folder_ids=[self.root.pk])
        self.folder("PROJECT", self.owner)
        response = self.post("restore", folder_ids=[self.root.pk])
        self.assertEqual(response.status_code, 409)
        self.root.refresh_from_db()
        self.assertIsNotNone(self.root.deleted_at)

    def test_restore_rolls_back_all_folders_if_a_concurrent_file_name_conflicts(self):
        self.post("trash", folder_ids=[self.root.pk])
        original_update = QuerySet.update
        def competing_name(queryset, **values):
            if queryset.model is File and values == {"deleted_at": None}:
                raise IntegrityError("Simulated concurrent file name collision")
            return original_update(queryset, **values)
        with patch.object(QuerySet, "update", competing_name):
            response = self.post("restore", folder_ids=[self.root.pk])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Folder.objects.filter(workspace=self.workspace, deleted_at__isnull=False).count(), 2)
        self.assertEqual(File.objects.filter(workspace=self.workspace, deleted_at__isnull=False).count(), 3)

    def test_file_names_are_unique_across_workspace_creators_and_case(self):
        self.file("REPORT.TXT", self.owner)
        name = unique_upload_name(File, "file_name", "report.txt", owner=self.editor, workspace=self.workspace)
        self.assertEqual(name, "report (2).txt")
        self.file("REPORT (COPY).TXT", self.owner)
        name = unique_copy_name(File, "file_name", "report.txt", owner=self.editor, workspace=self.workspace)
        self.assertEqual(name, "report (copy 2).txt")

    def test_copy_names_fit_database_limits_and_ignore_trashed_names(self):
        name = "a" * 251 + ".txt"
        copied = unique_copy_name(File, "file_name", name, owner=self.editor, workspace=self.workspace)
        self.assertLessEqual(len(copied), 255)
        self.assertTrue(copied.endswith(".txt"))
        folder_name = _unique_copy_folder_name(self.editor, self.tenant, None, "a" * 255, workspace=self.workspace)
        self.assertLessEqual(len(folder_name), 255)
        removed = self.file("gone (copy).txt", self.editor)
        removed.deleted_at = timezone.now()
        removed.save(update_fields=["deleted_at"])
        self.assertEqual(unique_copy_name(File, "file_name", "gone.txt", owner=self.editor, workspace=self.workspace), "gone (copy).txt")

    def test_duplicate_file_inside_another_creators_folder_follows_publication_ownership(self):
        def publish(session, plaintext, actor):
            copied = self.file(session.client_name, session.target_folder.owner, session.target_folder)
            version = FileVersion.objects.create(tenant=self.tenant, file=copied, version_number=1, state="available", size_bytes=3, is_current=True)
            config = StorageConfig.objects.create(tenant=self.tenant, provider="s3", status="active")
            StorageLocation.objects.create(tenant=self.tenant, file_version=version, storage_config=config, object_ref="primary/" + uuid.uuid4().hex, state="available")
            return {"file_id": copied.pk}
        with patch("files.views._decrypt_file", return_value=b"abc"), patch("files.quota.reserve_upload_quota"), patch("files.quota.finalize_upload_quota"), patch("files.finalization.finalize_verified_upload", side_effect=publish):
            response = self.post("duplicate", file_ids=[self.first.pk])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(File.objects.filter(folder=self.root, file_name="owner (copy).txt", owner=self.owner).exists())

    def test_duplicate_mixed_creator_tree_copies_every_accessible_descendant(self):
        def duplicate(source, *, actor, tenant, workspace, target_folder, target_name):
            copied = self.file(target_name, actor, target_folder)
            return copied, "primary/" + uuid.uuid4().hex
        with patch("dashboard.drive_api._duplicate_encrypted_file", side_effect=duplicate):
            response = self.post("duplicate", folder_ids=[self.root.pk])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 5)
        copied_root = Folder.objects.get(workspace=self.workspace, folder_name="Project (copy)")
        self.assertEqual(File.objects.filter(folder=copied_root).count(), 1)
        self.assertEqual(File.objects.filter(folder__parent=copied_root).count(), 2)
