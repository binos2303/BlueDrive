from cryptography.exceptions import InvalidTag
from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership
from files.models import File, FileVersion, StorageConfig, StorageLocation
from files.views import _safe_download_filename


User = get_user_model()


class DownloadSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="download-owner", password="secret")
        self.file = File.objects.create(
            tenant=self.user.personal_tenant,
            owner=self.user,
            file_name='report "final".pdf',
            file_path="uploads/report.enc",
            file_size=12,
            mime_type="application/pdf",
        )
        self.version = FileVersion.objects.create(
            tenant=self.file.tenant,
            file=self.file,
            version_number=1,
            state=FileVersion.State.AVAILABLE,
            size_bytes=12,
            mime_type="application/pdf",
            is_current=True,
        )
        # A current AVAILABLE version is downloadable only after its object is
        # published to an active PRIMARY storage location. Model that valid
        # state in download-success tests rather than bypassing the guard.
        self.storage_config = StorageConfig.objects.create(
            tenant=self.file.tenant,
            provider=StorageConfig.Provider.MINIO,
            status=StorageConfig.Status.ACTIVE,
        )
        self.storage_location = StorageLocation.objects.create(
            tenant=self.file.tenant,
            file_version=self.version,
            storage_config=self.storage_config,
            object_ref=f"primary/tests/{self.version.pk}",
            state=StorageLocation.State.AVAILABLE,
            size_bytes=12,
        )
        self.client.force_login(self.user)

    def test_private_file_is_not_downloadable_by_another_user(self):
        other = User.objects.create_user(username="download-other", password="secret")
        self.client.force_login(other)
        response = self.client.get(reverse("file_download", args=[self.file.pk]))
        self.assertEqual(response.status_code, 404)

    def test_removed_or_suspended_membership_cannot_download(self):
        for status in (Membership.Status.REVOKED, Membership.Status.SUSPENDED):
            with self.subTest(status=status):
                Membership.objects.filter(
                    user=self.user, tenant=self.file.tenant
                ).update(status=status)
                response = self.client.get(
                    reverse("file_download", args=[self.file.pk]),
                    HTTP_ACCEPT="application/octet-stream, application/json",
                )
                self.assertEqual(response.status_code, 403)
                Membership.objects.filter(
                    user=self.user, tenant=self.file.tenant
                ).update(status=Membership.Status.ACTIVE)

    def test_inactive_user_cannot_download(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        response = self.client.get(
            reverse("file_download", args=[self.file.pk]),
            HTTP_ACCEPT="application/octet-stream, application/json",
        )
        self.assertIn(response.status_code, (302, 403))

    def test_non_available_states_are_not_released_and_explain_status_to_owner(self):
        for state in (
            FileVersion.State.SCANNING,
            FileVersion.State.QUARANTINED,
            FileVersion.State.FAILED,
        ):
            with self.subTest(state=state):
                FileVersion.objects.filter(pk=self.version.pk).update(state=state)
                response = self.client.get(
                    reverse("file_download", args=[self.file.pk]),
                    HTTP_ACCEPT="application/octet-stream, application/json",
                )
                self.assertEqual(response.status_code, 409)
                self.assertIn("detail", response.json())
        FileVersion.objects.filter(pk=self.version.pk).update(
            state=FileVersion.State.AVAILABLE
        )

    def test_download_is_attachment_private_and_has_safe_headers(self):
        from unittest.mock import patch

        with patch("files.views._decrypt_file", return_value=b"verified bytes"):
            response = self.client.get(reverse("file_download", args=[self.file.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
        self.assertIn('filename="report \\\"final\\\".pdf"', response["Content-Disposition"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def test_download_without_available_primary_location_is_blocked(self):
        from django.urls import reverse

        self.storage_location.state = StorageLocation.State.ERROR
        self.storage_location.save(update_fields=["state", "updated_at"])
        response = self.client.get(
            reverse("file_download", args=[self.file.pk]),
            HTTP_ACCEPT="application/octet-stream, application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("primary storage", response.json()["detail"].lower())

    def test_download_filename_cannot_inject_headers_or_paths(self):
        self.assertEqual(
            _safe_download_filename("../unsafe\\name\r\nX-Evil: yes.pdf"),
            ".._unsafe_nameX-Evil: yes.pdf",
        )

    def test_repeated_download_requests_are_reauthorized(self):
        from unittest.mock import patch

        url = reverse("file_download", args=[self.file.pk])
        with patch("files.views._decrypt_file", return_value=b"verified") as decrypt:
            first = self.client.get(url)
            second = self.client.get(url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(decrypt.call_count, 2)

    def test_integrity_failure_and_missing_object_return_errors_not_success_redirects(self):
        from unittest.mock import patch

        url = reverse("file_download", args=[self.file.pk])
        with patch("files.views._decrypt_file", side_effect=InvalidTag):
            corrupt = self.client.get(url, HTTP_ACCEPT="application/octet-stream, application/json")
        self.assertEqual(corrupt.status_code, 422)
        self.assertIn("integrity", corrupt.json()["detail"].lower())

        with patch("files.views._decrypt_file", side_effect=Http404):
            missing = self.client.get(url, HTTP_ACCEPT="application/octet-stream, application/json")
        self.assertEqual(missing.status_code, 404)

    def test_preview_only_serves_allowlisted_types_inline(self):
        from unittest.mock import patch

        self.file.mime_type = "application/pdf"
        self.file.save(update_fields=["mime_type"])
        response = self.client.get(
            reverse("file_view", args=[self.file.pk]),
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 409)

        self.file.mime_type = "image/png"
        self.file.save(update_fields=["mime_type"])
        with patch("files.views._decrypt_file", return_value=b"png-bytes"):
            response = self.client.get(reverse("file_view", args=[self.file.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response["Content-Disposition"].startswith("inline;"))
        self.assertEqual(response["Content-Security-Policy"], "sandbox")

    def test_trashed_file_is_unavailable(self):
        self.file.deleted_at = "2026-10-01T00:00:00Z"
        self.file.save(update_fields=["deleted_at"])
        response = self.client.get(reverse("file_download", args=[self.file.pk]))
        self.assertEqual(response.status_code, 404)
