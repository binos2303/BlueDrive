from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from files.models import File
from folders.models import Folder
from logs.models import ActivityLog


class DriveSortAndRecentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="sort_user",
            password="TestPass123!",
        )
        self.client.force_login(self.user)
        self.folder_b = Folder.objects.create(owner=self.user, folder_name="Zeta")
        self.folder_a = Folder.objects.create(owner=self.user, folder_name="Alpha")
        self.file_b = File.objects.create(owner=self.user, file_name="zeta.txt", file_size=200)
        self.file_a = File.objects.create(owner=self.user, file_name="alpha.txt", file_size=100)

    def test_dashboard_supports_name_sort(self):
        response = self.client.get(reverse("dashboard"), {"sort": "name", "direction": "asc"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([f.folder_name for f in response.context["folders"]], ["Alpha", "Zeta"])
        self.assertEqual([f.file_name for f in response.context["files"]], ["alpha.txt", "zeta.txt"])

    def test_recent_uses_resource_linked_view_activity(self):
        self.file_a.last_accessed_at = timezone.now()
        self.file_a.save(update_fields=["last_accessed_at"])
        ct = ContentType.objects.get_for_model(File)
        ActivityLog.objects.create(
            user=self.user,
            action=ActivityLog.Action.VIEW,
            description="Viewed alpha.txt",
            content_type=ct,
            object_id=self.file_a.id,
        )
        response = self.client.get(reverse("recent"))
        self.assertEqual(response.status_code, 200)
        recent_file = next(item for item in response.context["recent_files"] if item.id == self.file_a.id)
        self.assertEqual(recent_file.recent_action, "View")
