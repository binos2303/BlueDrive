import base64
import os

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from files.models import File
from folders.models import Folder
from security.aes_service import (
    build_file_aad,
    encrypt_bytes,
    generate_dek,
    get_master_key,
    wrap_dek,
)

from .models import Share


class SharingAccessTests(TestCase):
    def setUp(self):
        os.environ["SECUREDRIVE_AES_KEY"] = base64.b64encode(
            os.urandom(32)
        ).decode()

        self.user_a = User.objects.create_user(
            username="user_a",
            password="TestPass123!",
        )
        self.user_b = User.objects.create_user(
            username="user_b",
            password="TestPass123!",
        )

        self.folder_a = Folder.objects.create(
            owner=self.user_a,
            folder_name="Shared Folder",
        )

        self.file_a = self._create_encrypted_file(
            owner=self.user_a,
            folder=self.folder_a,
            name="secret.txt",
            plaintext=b"secret content",
            mime_type="text/plain",
        )

    def _create_encrypted_file(
        self,
        *,
        owner,
        folder,
        name,
        plaintext,
        mime_type,
    ):
        drive_file = File.objects.create(
            owner=owner,
            folder=folder,
            file_name=name,
            file_size=len(plaintext),
            mime_type=mime_type,
            hash_sha256="",
            is_encrypted=True,
            encryption_version=1,
        )

        aad = build_file_aad(
            owner_id=owner.id,
            file_id=drive_file.id,
            version=drive_file.encryption_version,
        )
        dek = generate_dek()
        ciphertext, nonce = encrypt_bytes(
            plaintext,
            dek,
            aad,
        )
        wrapped_dek, dek_nonce = wrap_dek(
            dek,
            get_master_key(),
        )

        drive_file.file_path.save(
            f"tests-{drive_file.id}.enc",
            ContentFile(ciphertext),
            save=False,
        )
        drive_file.encryption_nonce = nonce
        drive_file.wrapped_dek = wrapped_dek
        drive_file.dek_nonce = dek_nonce
        drive_file.save(
            update_fields=[
                "file_path",
                "encryption_nonce",
                "wrapped_dek",
                "dek_nonce",
                "updated_at",
            ]
        )
        return drive_file

    def _share_file(self, recipient=None):
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("share_file", args=[self.file_a.id]),
            {"username": recipient or self.user_b.username},
        )
        self.assertEqual(response.status_code, 302)
        return Share.objects.get(
            file=self.file_a,
            receiver=self.user_b,
        )

    def test_shared_file_can_view_and_download(self):
        share = self._share_file()

        self.client.force_login(self.user_b)

        view_response = self.client.get(
            reverse("file_view", args=[self.file_a.id])
        )
        self.assertEqual(view_response.status_code, 200)
        self.assertEqual(
            b"".join(view_response.streaming_content),
            b"secret content",
        )

        download_response = self.client.get(
            reverse("file_download", args=[self.file_a.id])
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertIn(
            'attachment; filename="secret.txt"',
            download_response["Content-Disposition"],
        )
        self.assertTrue(Share.objects.filter(id=share.id).exists())

    def test_editor_can_rename_shared_file(self):
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("share_file", args=[self.file_a.id]),
            {"username": self.user_b.username, "permission": Share.Permission.EDITOR},
        )
        self.assertEqual(response.status_code, 302)
        share = Share.objects.get(file=self.file_a, receiver=self.user_b)
        self.assertEqual(share.permission, Share.Permission.EDITOR)

        self.client.force_login(self.user_b)
        response = self.client.post(
            reverse("file_rename", args=[self.file_a.id]),
            {"file_name": "renamed.txt"},
        )
        self.assertEqual(response.status_code, 302)
        self.file_a.refresh_from_db()
        self.assertEqual(self.file_a.file_name, "renamed.txt")

    def test_viewer_cannot_rename_shared_file(self):
        self._share_file()
        self.client.force_login(self.user_b)
        response = self.client.post(
            reverse("file_rename", args=[self.file_a.id]),
            {"file_name": "renamed.txt"},
        )
        self.assertEqual(response.status_code, 302)
        self.file_a.refresh_from_db()
        self.assertEqual(self.file_a.file_name, "secret.txt")

    def test_share_accepts_email_address(self):
        self.user_b.email = "receiver@example.com"
        self.user_b.save(update_fields=["email"])

        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("share_file", args=[self.file_a.id]),
            {"username": "RECEIVER@example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Share.objects.filter(
                file=self.file_a, receiver=self.user_b
            ).exists()
        )

    def test_owner_can_revoke_share(self):
        share = self._share_file()

        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("revoke_share", args=[share.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Share.objects.filter(id=share.id).exists())

    def test_receiver_cannot_revoke_share(self):
        share = self._share_file()

        self.client.force_login(self.user_b)
        response = self.client.post(
            reverse("revoke_share", args=[share.id])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Share.objects.filter(id=share.id).exists())

    def test_search_includes_soft_deleted_items(self):
        self.file_a.deleted_at = "2026-08-01T00:00:00Z"
        self.file_a.save(update_fields=["deleted_at"])

        self.folder_a.deleted_at = "2026-08-01T00:00:00Z"
        self.folder_a.save(update_fields=["deleted_at"])

        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse("search"),
            {"q": "secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "secret.txt")

        response = self.client.get(
            reverse("search"),
            {"q": "Shared Folder"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shared Folder")

    def test_other_user_cannot_open_private_folder_or_file(self):
        self.client.force_login(self.user_b)

        response = self.client.get(
            reverse("folder_open", args=[self.folder_a.id])
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.get(
            reverse("file_view", args=[self.file_a.id])
        )
        self.assertEqual(response.status_code, 404)


class SharingFolderTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(
            username="folder_owner",
            password="TestPass123!",
        )
        self.user_b = User.objects.create_user(
            username="folder_receiver",
            password="TestPass123!",
        )
        self.folder = Folder.objects.create(
            owner=self.user_a,
            folder_name="Project",
        )
        self.child = Folder.objects.create(
            owner=self.user_a,
            folder_name="Documents",
            parent=self.folder,
        )

    def test_folder_share_becomes_unavailable_after_soft_delete(self):
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("share_folder", args=[self.folder.id]),
            {
                "username": self.user_b.username,
            },
        )
        self.assertEqual(response.status_code, 302)

        self.folder.deleted_at = "2026-08-01T00:00:00Z"
        self.folder.save(update_fields=["deleted_at"])

        self.client.force_login(self.user_b)
        response = self.client.get(
            reverse("folder_open", args=[self.folder.id])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Share.objects.filter(folder=self.folder, receiver=self.user_b).exists())

    def test_shared_folder_details_becomes_unavailable_after_soft_delete(self):
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("share_folder", args=[self.folder.id]),
            {"username": self.user_b.username},
        )
        self.assertEqual(response.status_code, 302)

        self.folder.deleted_at = "2026-08-01T00:00:00Z"
        self.folder.save(update_fields=["deleted_at"])

        self.client.force_login(self.user_b)
        response = self.client.get(
            reverse("folder_details", args=[self.folder.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_shared_folder_details_excludes_deleted_descendants(self):
        self.child.deleted_at = "2026-08-01T00:00:00Z"
        self.child.save(update_fields=["deleted_at"])

        deleted_child = Folder.objects.create(
            owner=self.user_a,
            folder_name="Deleted child",
            parent=self.folder,
            deleted_at="2026-08-01T00:00:00Z",
        )

        File.objects.create(
            owner=self.user_a,
            folder=self.folder,
            file_name="active.txt",
        )

        File.objects.create(
            owner=self.user_a,
            folder=deleted_child,
            file_name="deleted.txt",
            deleted_at="2026-08-01T00:00:00Z",
        )

        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("share_folder", args=[self.folder.id]),
            {"username": self.user_b.username},
        )
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.user_b)
        response = self.client.get(
            reverse("folder_details", args=[self.folder.id])
        )

        self.assertEqual(response.status_code, 200)

        payload = response.json()

        self.assertEqual(payload["folder_count"], 0)
        self.assertEqual(payload["file_count"], 1)
        self.assertEqual(payload["location"], "Shared with me")
        self.assertEqual(payload["access"], "Viewer")
        self.assertEqual(payload["shared_by"], self.user_a.username)

    def test_inherited_share_allows_child_folder_details(self):
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("share_folder", args=[self.folder.id]),
            {"username": self.user_b.username},
        )
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.user_b)
        response = self.client.get(
            reverse("folder_details", args=[self.child.id])
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["name"], "Documents")
        self.assertEqual(payload["access"], "Viewer")
        self.assertEqual(payload["shared_by"], self.user_a.username)

    def test_direct_child_share_survives_parent_share_revoke(self):
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("share_folder", args=[self.folder.id]),
            {"username": self.user_b.username},
        )
        self.assertEqual(response.status_code, 302)
        parent_share = Share.objects.get(
            folder=self.folder,
            receiver=self.user_b,
        )

        response = self.client.post(
            reverse("share_folder", args=[self.child.id]),
            {"username": self.user_b.username},
        )
        self.assertEqual(response.status_code, 302)
        child_share = Share.objects.get(
            folder=self.child,
            receiver=self.user_b,
        )

        response = self.client.post(
            reverse("revoke_share", args=[parent_share.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Share.objects.filter(id=parent_share.id).exists())
        self.assertTrue(Share.objects.filter(id=child_share.id).exists())

        self.client.force_login(self.user_b)
        response = self.client.get(
            reverse("folder_open", args=[self.child.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_shared_child_file_details_exposes_shared_location_only(self):
        child_file = File.objects.create(
            owner=self.user_a,
            folder=self.child,
            file_name="child.txt",
        )
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("share_folder", args=[self.folder.id]),
            {"username": self.user_b.username},
        )
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.user_b)
        response = self.client.get(
            reverse("file_details", args=[child_file.id])
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["location"], "Shared with me / Documents")
        self.assertEqual(payload["access"], "Viewer")
        self.assertEqual(payload["shared_by"], self.user_a.username)

    def test_deleted_shared_file_becomes_unavailable(self):
        # Reuse the file fixture from SharingAccessTests semantics with a simple DB object.
        file_obj = File.objects.create(
            owner=self.user_a,
            folder=self.folder,
            file_name="deleted.txt",
            deleted_at="2026-08-01T00:00:00Z",
        )
        Share.objects.create(
            owner=self.user_a,
            receiver=self.user_b,
            file=file_obj,
        )

        self.client.force_login(self.user_b)
        response = self.client.get(reverse("file_view", args=[file_obj.id]))
        self.assertEqual(response.status_code, 404)

        response = self.client.get(reverse("file_download", args=[file_obj.id]))
        self.assertEqual(response.status_code, 404)

    def test_permanent_delete_removes_share_target(self):
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("share_folder", args=[self.folder.id]),
            {
                "username": self.user_b.username,
            },
        )
        self.assertEqual(response.status_code, 302)

        share = Share.objects.get(
            folder=self.folder,
            receiver=self.user_b,
        )

        self.folder.delete()

        self.client.force_login(self.user_b)
        response = self.client.get(
            reverse("folder_open", args=[share.folder_id])
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            Share.objects.filter(id=share.id).exists()
        )


class AuthorizationIDORTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(
            username="idor_a",
            password="TestPass123!",
        )
        self.user_b = User.objects.create_user(
            username="idor_b",
            password="TestPass123!",
        )
        self.folder_a = Folder.objects.create(
            owner=self.user_a,
            folder_name="Private",
        )
        self.file_a = File.objects.create(
            owner=self.user_a,
            folder=self.folder_a,
            file_name="secret.txt",
        )

    def test_other_user_cannot_open_private_folder(self):
        self.client.force_login(self.user_b)
        response = self.client.get(
            reverse("folder_open", args=[self.folder_a.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_other_user_cannot_download_private_file(self):
        self.client.force_login(self.user_b)
        response = self.client.get(
            reverse("file_download", args=[self.file_a.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_other_user_cannot_view_private_file(self):
        self.client.force_login(self.user_b)
        response = self.client.get(
            reverse("file_view", args=[self.file_a.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_other_user_cannot_delete_private_file(self):
        self.client.force_login(self.user_b)
        response = self.client.post(
            reverse("file_move_to_trash", args=[self.file_a.id])
        )
        self.assertEqual(response.status_code, 404)
        self.file_a.refresh_from_db()
        self.assertIsNone(self.file_a.deleted_at)

    def test_trashed_folder_cannot_be_shared_as_new_share(self):
        self.folder_a.deleted_at = "2026-01-01T00:00:00Z"
        self.folder_a.save(update_fields=["deleted_at"])

        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("share_folder", args=[self.folder_a.id]),
            {
                "username": self.user_b.username,
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            Share.objects.filter(
                folder=self.folder_a,
                receiver=self.user_b,
            ).exists()
        )
