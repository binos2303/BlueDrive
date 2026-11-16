"""Drive metadata queries and workspace/direct-share permission boundaries."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import Membership, Workspace, WorkspaceMembership
from files.models import File
from folders.models import Folder
from folders.tree_service import folder_subtree
from sharing.models import Share


class DriveListingQueryTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="listing-owner")
        self.editor = users.objects.create_user(username="listing-editor")
        self.tenant = self.owner.personal_tenant
        self.workspace = Workspace.objects.create(tenant=self.tenant, name="Listing", slug="listing")
        member = Membership.objects.create(tenant=self.tenant, user=self.editor, role="member")
        self.assignment = WorkspaceMembership.objects.create(workspace=self.workspace, membership=member, role="editor")
        self.client.force_login(self.editor)

    def folder(self, name, parent=None, **kwargs):
        return Folder.objects.create(tenant=self.tenant, workspace=self.workspace, owner=self.owner,
                                     folder_name=name, parent=parent, **kwargs)

    def file(self, name, folder=None):
        return File.objects.create(tenant=self.tenant, workspace=self.workspace, owner=self.owner,
                                   file_name=name, file_size=1, folder=folder)

    def listing(self, folder=None):
        return self.client.get("/drive/api/items/", {"folder": folder.pk} if folder else {},
                               HTTP_X_WORKSPACE_ID=str(self.workspace.pk))

    def test_root_query_count_does_not_grow_per_item(self):
        counts = []
        for total in (10, 30):
            for number in range(File.objects.filter(workspace=self.workspace).count(), total):
                self.file(f"File {number:03}.txt")
            with CaptureQueriesContext(connection) as queries:
                response = self.listing()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["items"]), total)
            self.assertTrue(all(item["canManage"] for item in response.json()["items"]))
            counts.append(len(queries))
        print(f"Workspace root listing SQL: 10 files={counts[0]}, 30 files={counts[1]}")
        self.assertLessEqual(counts[1], counts[0] + 2)

    def test_editor_can_manage_colleagues_folders_and_viewer_cannot(self):
        root = self.folder("Colleague folder")
        self.folder("Nested", root)
        response = self.listing()
        self.assertTrue(response.json()["items"][0]["canManage"])
        self.assignment.role = "viewer"
        self.assignment.save(update_fields=["role"])
        response = self.listing()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["items"][0]["canManage"])

    def test_deleted_ancestor_still_blocks_workspace_editor_listing(self):
        root = self.folder("Deleted", deleted_at=timezone.now())
        child = self.folder("Hidden child", root)
        self.file("Hidden.txt", child)
        self.assertEqual(self.listing(child).status_code, 404)

    def test_workspace_viewer_retains_explicit_editor_share(self):
        self.assignment.role = "viewer"
        self.assignment.save(update_fields=["role"])
        file = self.file("Explicit editor.txt")
        self.file("Viewer only.txt")
        Share.objects.create(tenant=self.tenant, owner=self.owner, receiver=self.editor, file=file, permission="editor")
        response = self.listing()
        self.assertEqual(response.status_code, 200)
        rows = {item["name"]: item for item in response.json()["items"]}
        self.assertTrue(rows["Explicit editor.txt"]["canManage"])
        self.assertFalse(rows["Viewer only.txt"]["canManage"])

    def test_direct_share_retains_child_viewer_override_and_private_root(self):
        receiver = get_user_model().objects.create_user(username="listing-receiver")
        root = self.folder("Shared root")
        child = self.folder("Child", root)
        self.file("Inherited.txt", root)
        Share.objects.create(tenant=self.tenant, owner=self.owner, receiver=receiver, folder=root, permission="editor")
        Share.objects.create(tenant=self.tenant, owner=self.owner, receiver=receiver, folder=child, permission="viewer")
        self.client.force_login(receiver)
        response = self.listing(root)
        self.assertEqual(response.status_code, 200)
        rows = {item["name"]: item for item in response.json()["items"]}
        self.assertTrue(rows["Inherited.txt"]["canManage"])
        self.assertFalse(rows["Child"]["canManage"])
        self.assertEqual(self.listing().status_code, 404)

    def test_tree_batches_siblings_preserving_scope_and_parent_order(self):
        root = self.folder("Root")
        children = [self.folder(f"Child {number}", root) for number in range(12)]
        self.folder("Trashed child", root, deleted_at=timezone.now())
        self.folder("Unrelated root")
        with CaptureQueriesContext(connection) as queries:
            rows = folder_subtree(root)
        print(f"Folder subtree SQL: {len(rows)} nodes={len(queries)} queries")
        self.assertEqual([row.pk for row in rows], [root.pk, *[child.pk for child in children]])
        self.assertLessEqual(len(queries), 2)

    def test_tree_handles_cycles_and_deleted_owner_filters(self):
        root = self.folder("Root")
        child = self.folder("Child", root)
        grandchild = self.folder("Grandchild", child)
        Folder.objects.filter(pk=root.pk).update(parent=grandchild)
        root.refresh_from_db()
        self.assertEqual([row.pk for row in folder_subtree(root)], [root.pk, child.pk, grandchild.pk])
        self.assertEqual([row.pk for row in folder_subtree(root, owner=self.editor)], [root.pk])
        Folder.objects.filter(pk=child.pk).update(deleted_at=timezone.now())
        self.assertEqual([row.pk for row in folder_subtree(root)], [root.pk])
        self.assertEqual(len(folder_subtree(root, include_deleted=True)), 3)
