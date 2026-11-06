"""Sprint 2.4: direct Share JSON API security and consistency regression tests."""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.access import get_default_workspace
from accounts.models import Membership, WorkspaceMembership
from accounts.services import get_personal_tenant
from files.models import File
from folders.models import Folder
from logs.models import ActivityLog
from sharing.models import Share
from sharing.services import can_view_file

User = get_user_model()


class ShareManagementApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="share-api-owner", email="api-owner@example.test", password="secret123!",
        )
        self.receiver = User.objects.create_user(
            username="share-api-receiver", email="api-receiver@example.test", password="secret123!",
        )
        self.stranger = User.objects.create_user(
            username="share-api-stranger", email="api-stranger@example.test", password="secret123!",
        )
        self.tenant = get_personal_tenant(self.owner)
        self.workspace = get_default_workspace(self.tenant)
        self.folder = Folder.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner, folder_name="Team files",
        )
        self.file = File.objects.create(
            tenant=self.tenant, workspace=self.workspace, owner=self.owner,
            file_name="tasks.txt", mime_type="text/plain", file_size=5,
        )
        self.grant = Share.objects.create(
            owner=self.owner, receiver=self.receiver, tenant=self.tenant,
            file=self.file, permission=Share.Permission.VIEWER,
        )
        self.client.force_login(self.owner)
        self.list_url = reverse("drive_api_shares")
        self.detail_url = reverse("drive_api_share_detail", args=[self.grant.pk])

    def _patch(self, payload, **headers):
        return self.client.patch(self.detail_url, data=json.dumps(payload),
                                 content_type="application/json", **headers)

    def test_list_direct_grants_scoped_to_resource_owner_and_workspace(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["id"], self.grant.pk)
        self.assertEqual(response.json()["items"][0]["recipient"]["email"], self.receiver.email)
        self.assertIsNone(response.json()["item"])
        self.assertEqual(response["Cache-Control"], "private, no-store")

        response = self.client.get(self.list_url, {"kind": "file", "id": self.file.pk})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["can_manage"])
        self.assertEqual(response.json()["item"]["name"], "tasks.txt")
        self.assertEqual(response.json()["total"], 1)

    def test_empty_or_wrong_resource_does_not_disclose_other_user_grants(self):
        self.client.force_login(self.stranger)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["items"], [])
        response = self.client.get(self.list_url, {"kind": "file", "id": self.file.pk})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._patch({"permission": "editor"}).status_code, 404)
        self.assertEqual(self.client.delete(self.detail_url).status_code, 404)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.permission, Share.Permission.VIEWER)

    def test_list_only_own_shares_and_filter_by_kind(self):
        second = Share.objects.create(
            owner=self.owner, receiver=self.receiver, tenant=self.tenant,
            folder=self.folder, permission=Share.Permission.EDITOR,
        )
        response = self.client.get(self.list_url, {"kind": "folder", "id": self.folder.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()["items"]], [second.pk])
        response = self.client.get(self.list_url, {"page": "1", "page_size": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(response.json()["pages"], 2)
        self.assertEqual(len(response.json()["items"]), 1)
        response = self.client.get(self.list_url, {"page": "2", "page_size": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 1)

    def test_pagination_and_target_validation(self):
        for query in ({"page": "0"}, {"page_size": "51"}, {"page": "abc"},
                      {"kind": "file"}, {"id": str(self.file.pk)},
                      {"kind": "invalid", "id": str(self.file.pk)},
                      {"kind": "folder", "id": "true"}):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(self.list_url, query).status_code, 400)
        self.assertEqual(self.client.get(self.list_url, {"page": "2"}).status_code, 404)

    def test_patch_updates_and_audits_only_real_changes(self):
        response = self._patch({"permission": "editor"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["changed"])
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.permission, Share.Permission.EDITOR)
        self.assertEqual(ActivityLog.objects.filter(
            user=self.owner, action=ActivityLog.Action.SHARE,
        ).count(), 1)
        second = self._patch({"permission": "editor"})
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["changed"])
        self.assertEqual(ActivityLog.objects.filter(
            user=self.owner, action=ActivityLog.Action.SHARE,
        ).count(), 1)

    def test_patch_rejects_invalid_payload_without_side_effects(self):
        for body in ({}, {"permission": "owner"}, {"permission": 123},
                     {"permission": "viewer", "owner": 999}, []):
            with self.subTest(body=body):
                self.assertEqual(self._patch(body).status_code, 400)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.permission, Share.Permission.VIEWER)

    def test_revoke_removes_direct_grant_and_audits(self):
        self.assertTrue(can_view_file(self.file, self.receiver))
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["revoked"])
        self.assertFalse(Share.objects.filter(pk=self.grant.pk).exists())
        self.assertFalse(can_view_file(self.file, self.receiver))
        self.assertEqual(ActivityLog.objects.filter(
            user=self.owner, action=ActivityLog.Action.REVOKE_SHARE,
        ).count(), 1)
        self.assertEqual(self.client.delete(self.detail_url).status_code, 404)

    def test_trashed_resource_blocks_mutation_and_is_not_listed(self):
        self.file.deleted_at = timezone.now()
        self.file.save(update_fields=["deleted_at"])
        self.assertEqual(self._patch({"permission": "editor"}).status_code, 404)
        self.assertEqual(self.client.get(self.list_url).json()["total"], 0)
        self.assertEqual(self.client.delete(self.detail_url).status_code, 404)

    def test_legacy_change_and_revoke_use_same_audited_service(self):
        response = self.client.post(reverse("change_share_permission", args=[self.grant.pk]),
                                    {"permission": "editor"})
        self.assertEqual(response.status_code, 302)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.permission, Share.Permission.EDITOR)
        response = self.client.post(reverse("revoke_share", args=[self.grant.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Share.objects.filter(pk=self.grant.pk).exists())
        self.assertEqual(ActivityLog.objects.filter(
            user=self.owner, action=ActivityLog.Action.REVOKE_SHARE,
        ).count(), 1)

    def test_workspace_editor_cannot_manage_someone_elses_direct_grant(self):
        membership = Membership.objects.create(
            tenant=self.tenant, user=self.receiver,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=membership,
            role=WorkspaceMembership.Role.EDITOR, status=WorkspaceMembership.Status.ACTIVE,
        )
        self.client.force_login(self.receiver)
        headers = {"HTTP_X_WORKSPACE_ID": str(self.workspace.pk)}
        targeted = self.client.get(self.list_url, {"kind": "file", "id": self.file.pk}, **headers)
        self.assertEqual(targeted.status_code, 404)
        self.assertEqual(self._patch({"permission": "editor"}, **headers).status_code, 404)
        self.assertEqual(self.client.delete(self.detail_url, **headers).status_code, 404)
        attempted = self.client.post(
            reverse("drive_items_share_api"),
            data=json.dumps({"file_ids": [self.file.pk], "folder_ids": [],
                             "email": self.stranger.email, "permission": "editor"}),
            content_type="application/json", **headers,
        )
        self.assertEqual(attempted.status_code, 403)

    def test_revoking_direct_share_does_not_remove_workspace_membership_access(self):
        membership = Membership.objects.create(
            tenant=self.tenant, user=self.receiver,
            role=Membership.Role.MEMBER, status=Membership.Status.ACTIVE,
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace, membership=membership,
            role=WorkspaceMembership.Role.VIEWER, status=WorkspaceMembership.Status.ACTIVE,
        )
        self.assertEqual(self.client.delete(self.detail_url).status_code, 200)
        self.assertFalse(Share.objects.filter(pk=self.grant.pk).exists())
        self.assertTrue(can_view_file(self.file, self.receiver))

    def test_session_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.patch(self.detail_url, json.dumps({"permission": "editor"}),
                                      content_type="application/json").status_code, 403)
        self.assertEqual(client.delete(self.detail_url).status_code, 403)
        csrf = client.get(reverse("api-csrf"))
        self.assertEqual(csrf.status_code, 200)
        accepted = client.patch(
            self.detail_url, json.dumps({"permission": "editor"}), content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf.json()["csrfToken"],
        )
        self.assertEqual(accepted.status_code, 200, accepted.content)
