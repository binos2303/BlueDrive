"""Tests for directly shared Drive items crossing personal-tenant boundaries."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.access import get_default_workspace
from accounts.services import get_personal_tenant
from files.models import File
from folders.models import Folder
from sharing.models import Share


User = get_user_model()


class SharedDriveApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="share-owner",
            email="share-owner@example.test",
            password="test-password",
        )
        self.recipient = User.objects.create_user(
            username="share-recipient",
            email="share-recipient@example.test",
            password="test-password",
        )
        self.owner_tenant = get_personal_tenant(self.owner)
        self.owner_workspace = get_default_workspace(self.owner_tenant)
        self.private_folder = Folder.objects.create(
            tenant=self.owner_tenant,
            workspace=self.owner_workspace,
            owner=self.owner,
            folder_name="Shared project documents",
        )
        self.child_file = File.objects.create(
            tenant=self.owner_tenant,
            workspace=self.owner_workspace,
            owner=self.owner,
            folder=self.private_folder,
            file_name="project-plan.txt",
            file_path="uploads/project-plan.txt.enc",
            file_size=19,
            mime_type="text/plain",
        )
        self.unshared_folder = Folder.objects.create(
            tenant=self.owner_tenant,
            workspace=self.owner_workspace,
            owner=self.owner,
            folder_name="Confidential payroll",
        )
        self.direct_file = File.objects.create(
            tenant=self.owner_tenant,
            workspace=self.owner_workspace,
            owner=self.owner,
            file_name="budget-summary.txt",
            file_path="uploads/budget-summary.txt.enc",
            file_size=25,
            mime_type="text/plain",
        )
        Share.objects.create(
            tenant=self.owner_tenant,
            owner=self.owner,
            receiver=self.recipient,
            folder=self.private_folder,
            permission=Share.Permission.VIEWER,
        )
        Share.objects.create(
            tenant=self.owner_tenant,
            owner=self.owner,
            receiver=self.recipient,
            file=self.direct_file,
            permission=Share.Permission.VIEWER,
        )
        self.client = Client()
        self.client.force_login(self.recipient)

    def test_shared_view_lists_direct_shares_across_other_personal_tenant(self):
        response = self.client.get(reverse("drive_items_api"), {"view": "shared"})

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual([item["name"] for item in items], ["Shared project documents", "budget-summary.txt"])
        self.assertEqual(items[0]["owner"], self.owner.get_username())
        self.assertFalse(items[0]["canManage"])
        self.assertFalse(items[1]["canManage"])

    def test_recipient_can_browse_a_shared_folder_without_joining_sender_workspace(self):
        response = self.client.get(
            reverse("drive_items_api"),
            {"folder": str(self.private_folder.pk)},
        )

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual([item["name"] for item in items], ["project-plan.txt"])
        self.assertEqual(items[0]["workspaceId"], str(self.owner_workspace.pk))

    def test_unshared_folder_remains_not_found_to_recipient(self):
        response = self.client.get(
            reverse("drive_items_api"),
            {"folder": str(self.unshared_folder.pk)},
        )

        self.assertEqual(response.status_code, 404)

    def test_shared_search_only_returns_names_from_directly_shared_items(self):
        response = self.client.get(
            reverse("drive_items_api"),
            {"view": "shared", "q": "payroll"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])
        # Searching names of children inside a shared folder is not equivalent
        # to directly sharing each child as a root item in Shared with me.
        response = self.client.get(
            reverse("drive_items_api"),
            {"view": "shared", "q": "documents"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["name"] for item in response.json()["items"]], ["Shared project documents"])
