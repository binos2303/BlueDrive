from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import QuotaAccount
from files.models import File, FileVersion, StorageConfig, StorageLocation
from files.permanent_delete import permanently_delete_files
from logs.models import ActivityLog


class PermanentDeleteReplayTests(TestCase):
    def test_two_requests_using_same_legacy_snapshot_account_once(self):
        owner = get_user_model().objects.create_user(username="purge-replay-owner")
        tenant = owner.personal_tenant
        file = File.objects.create(
            tenant=tenant, owner=owner, file_name="trash.txt", file_size=12,
            deleted_at=timezone.now(),
        )
        other = File.objects.create(tenant=tenant, owner=owner, file_name="other.txt", file_size=12)
        quota = QuotaAccount.objects.get(tenant=tenant, scope="tenant")
        quota.used_bytes = 24
        quota.save(update_fields=["used_bytes"])

        # Cả hai request đã chọn cùng file trước khi request đầu commit.
        stale = File.objects.get(pk=file.pk)
        self.assertEqual(permanently_delete_files([file]), 1)
        self.assertEqual(permanently_delete_files([stale]), 0)
        quota.refresh_from_db()
        self.assertEqual(quota.used_bytes, other.file_size)
        self.assertTrue(File.objects.filter(pk=other.pk).exists())


class PermanentDeleteConcurrencyTests(TransactionTestCase):
    serialized_rollback = True

    def test_overlapping_delete_io_releases_quota_and_audits_once(self):
        owner = get_user_model().objects.create_user(username="concurrent-purge-owner")
        tenant = owner.personal_tenant
        file = File.objects.create(
            tenant=tenant, owner=owner, file_name="trash.txt", file_size=12, deleted_at=timezone.now(),
        )
        quota = QuotaAccount.objects.get(tenant=tenant, scope=QuotaAccount.Scope.TENANT)
        QuotaAccount.objects.filter(pk=quota.pk).update(used_bytes=24)
        version = FileVersion.objects.create(
            tenant=tenant, file=file, version_number=1, state=FileVersion.State.AVAILABLE, size_bytes=12,
        )
        location = StorageLocation.objects.create(
            tenant=tenant, file_version=version, storage_config=StorageConfig.objects.create(tenant=tenant, provider="s3"),
            object_ref="primary/concurrent-purge", state=StorageLocation.State.AVAILABLE,
        )
        barrier = Barrier(2)

        def delete_object(key):
            self.assertEqual(key, location.object_ref)
            self.assertFalse(connections["default"].in_atomic_block)
            barrier.wait(timeout=10)

        def audit(files):
            ActivityLog.objects.create(
                user=owner, tenant=tenant, action=ActivityLog.Action.PERMANENT_DELETE, description=str(len(files)),
            )

        def purge(_):
            try:
                return permanently_delete_files([File.objects.get(pk=file.pk)], on_deleted=audit)
            finally:
                connections.close_all()

        with patch("files.permanent_delete.adapter_for_location", return_value=Mock(delete_object=delete_object)):
            with ThreadPoolExecutor(max_workers=2) as workers:
                self.assertCountEqual(list(workers.map(purge, range(2))), [1, 0])
        quota.refresh_from_db()
        self.assertEqual(quota.used_bytes, 12)
        self.assertFalse(File.objects.filter(pk=file.pk).exists())
        self.assertEqual(ActivityLog.objects.filter(tenant=tenant, action=ActivityLog.Action.PERMANENT_DELETE).count(), 1)
