"""Recent lists authorized files active within the trailing seven days."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.access import get_default_workspace
from accounts.models import Membership, Workspace, WorkspaceMembership
from files.models import File
from folders.models import Folder
from logs.models import SearchHistory


class RecentFilesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="recent-seven-days")
        self.tenant = self.user.personal_tenant
        self.workspace = get_default_workspace(self.tenant)
        self.now = timezone.now()
        self.client.force_login(self.user)

    def file(self, name, *, updated=None, accessed=None, **kwargs):
        file = File.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.user,
            file_name=name, file_size=1, **kwargs,
        )
        File.objects.filter(pk=file.pk).update(
            updated_at=updated or self.now, last_accessed_at=accessed,
        )
        return file

    def recent(self, **params):
        with patch("dashboard.views.timezone.now", return_value=self.now):
            response = self.client.get(reverse("drive_items_api"), {"view": "recent", **params})
        self.assertEqual(response.status_code, 200)
        return response.json()["items"]

    def test_seven_day_boundary_is_inclusive_and_excludes_older_or_future_activity(self):
        cutoff = self.now - timedelta(days=7)
        boundary = self.file("Boundary.txt", updated=cutoff)
        newest = self.file("Now.txt")
        self.file("Too old.txt", updated=cutoff - timedelta(microseconds=1))
        self.file("Future.txt", updated=self.now + timedelta(seconds=1))
        self.assertEqual([row["id"] for row in self.recent()], [newest.pk, boundary.pk])

    def test_recent_access_revives_old_file_and_recent_edit_overrides_old_access(self):
        old = self.now - timedelta(days=30)
        opened = self.file("Opened.txt", updated=old, accessed=self.now - timedelta(hours=1))
        edited = self.file("Edited.txt", updated=self.now - timedelta(hours=2), accessed=old)
        self.file("Inactive.txt", updated=old, accessed=self.now - timedelta(days=8))
        rows = self.recent()
        self.assertEqual([row["id"] for row in rows], [opened.pk, edited.pk])
        self.assertEqual(rows[0]["modified"], (self.now - timedelta(hours=1)).isoformat())

    def test_recent_contains_files_only_and_leaves_drive_contents_unchanged(self):
        Folder.objects.create(tenant=self.tenant, workspace=self.workspace, owner=self.user, folder_name="Active folder")
        active = self.file("Active.txt")
        old = self.file("Old.txt", updated=self.now - timedelta(days=8))
        self.assertEqual([row["id"] for row in self.recent()], [active.pk])
        response = self.client.get(reverse("drive_items_api"))
        self.assertEqual({row["name"] for row in response.json()["items"]}, {"Active folder", active.file_name, old.file_name})

    def test_recent_search_cannot_bypass_window_or_include_folders(self):
        wanted = self.file("Report new.txt")
        self.file("Report old.txt", updated=self.now - timedelta(days=8))
        self.file("Unrelated.txt")
        Folder.objects.create(tenant=self.tenant, workspace=self.workspace, owner=self.user, folder_name="Report folder")
        self.assertEqual([row["id"] for row in self.recent(q="report")], [wanted.pk])
        self.assertEqual(SearchHistory.objects.get(user=self.user, query="report").result_count, 1)

    def test_recent_excludes_trash_deleted_ancestors_and_other_workspaces(self):
        visible = self.file("Visible.txt")
        self.file("Trashed.txt", deleted_at=self.now)
        parent = Folder.objects.create(tenant=self.tenant, workspace=self.workspace, owner=self.user,
                                       folder_name="Trashed", deleted_at=self.now)
        child = Folder.objects.create(tenant=self.tenant, workspace=self.workspace, owner=self.user,
                                      folder_name="Hidden child", parent=parent)
        self.file("Hidden.txt", folder=child)
        other = Workspace.objects.create(tenant=self.tenant, name="Other", slug="recent-other")
        File.objects.create(tenant=self.tenant, workspace=other, owner=self.user, file_name="Other workspace.txt", file_size=1)
        self.assertEqual([row["id"] for row in self.recent()], [visible.pk])

    def test_activity_timeline_retains_fourteen_days_without_changing_recent(self):
        old = self.now - timedelta(days=10)
        file = self.file("Timeline file.txt", updated=old)
        folder = Folder.objects.create(tenant=self.tenant, workspace=self.workspace, owner=self.user, folder_name="Timeline folder")
        Folder.objects.filter(pk=folder.pk).update(updated_at=old)
        self.file("Outside timeline.txt", updated=self.now - timedelta(days=15))
        self.assertEqual(self.recent(), [])
        rows = self.recent(view="timeline")
        self.assertEqual({row["name"] for row in rows}, {file.file_name, folder.folder_name})

    def test_activity_timeline_requires_workspace_manager(self):
        editor = get_user_model().objects.create_user(username="recent-editor")
        member = Membership.objects.create(tenant=self.tenant, user=editor, role="member")
        WorkspaceMembership.objects.create(workspace=self.workspace, membership=member, role="editor")
        self.client.force_login(editor)
        response = self.client.get(reverse("drive_items_api"), {"view": "timeline"},
                                   HTTP_X_WORKSPACE_ID=str(self.workspace.pk))
        self.assertEqual(response.status_code, 404)
