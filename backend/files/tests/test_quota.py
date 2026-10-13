from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection
from django.test import TestCase, TransactionTestCase

from accounts.models import QuotaAccount, Tenant
from files.models import File, QuotaReservation, UploadSession
from files.quota import (
    QuotaExceeded,
    QuotaStateError,
    finalize_upload_quota,
    reserve_upload_quota,
)
from files.services import clone_encrypted_file_with_quota


User = get_user_model()


class QuotaReservationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="quota-user")
        self.tenant = self.user.personal_tenant
        self.account = QuotaAccount.objects.get(
            tenant=self.tenant,
            scope=QuotaAccount.Scope.TENANT,
        )
        self.account.limit_bytes = 100
        self.account.save(update_fields=["limit_bytes", "updated_at"])

    def create_upload(self, *, size=70, state=UploadSession.State.INITIATED):
        return UploadSession.objects.create(
            tenant=self.tenant,
            initiated_by=self.user,
            client_name="sample.bin",
            expected_size_bytes=size,
            state=state,
            expires_at="2035-01-01T00:00:00Z",
        )

    def test_reservation_is_idempotent_and_completion_consumes_actual_size(self):
        upload = self.create_upload()

        first = reserve_upload_quota(upload.pk, self.user)
        second = reserve_upload_quota(upload.pk, self.user)

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].pk, second[0].pk)
        self.account.refresh_from_db()
        self.assertEqual(self.account.reserved_bytes, 70)
        self.assertEqual(QuotaReservation.objects.count(), 1)

        finalize_upload_quota(
            upload.pk,
            completed=True,
            actual_size_bytes=64,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.reserved_bytes, 0)
        self.assertEqual(self.account.used_bytes, 64)
        self.assertEqual(
            QuotaReservation.objects.get().state,
            QuotaReservation.State.CONSUMED,
        )
        finalize_upload_quota(
            upload.pk,
            completed=True,
            actual_size_bytes=64,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.used_bytes, 64)

    def test_failed_or_canceled_upload_releases_reservation(self):
        upload = self.create_upload()
        reserve_upload_quota(upload.pk, self.user)

        finalize_upload_quota(upload.pk, completed=False)
        self.account.refresh_from_db()

        self.assertEqual(self.account.reserved_bytes, 0)
        self.assertEqual(self.account.used_bytes, 0)
        self.assertEqual(
            QuotaReservation.objects.get().state,
            QuotaReservation.State.RELEASED,
        )

    def test_quota_limit_rejects_reservation_without_changing_counters(self):
        upload = self.create_upload(size=101)

        with self.assertRaises(QuotaExceeded):
            reserve_upload_quota(upload.pk, self.user)

        self.account.refresh_from_db()
        self.assertEqual(self.account.reserved_bytes, 0)
        self.assertFalse(QuotaReservation.objects.exists())

    def test_business_upload_requires_member_allocation_and_checks_both_limits(self):
        self.tenant.kind = Tenant.Kind.BUSINESS
        self.tenant.personal_owner = None
        self.tenant.save(update_fields=["kind", "personal_owner"])
        member_account = QuotaAccount.objects.create(
            tenant=self.tenant,
            scope=QuotaAccount.Scope.MEMBER,
            user=self.user,
            limit_bytes=50,
        )
        upload = self.create_upload(size=60)

        with self.assertRaises(QuotaExceeded):
            reserve_upload_quota(upload.pk, self.user)

        self.account.refresh_from_db()
        member_account.refresh_from_db()
        self.assertEqual(self.account.reserved_bytes, 0)
        self.assertEqual(member_account.reserved_bytes, 0)

    def test_only_initiator_can_reserve_and_completed_upload_cannot_start_reservation(self):
        other_user = User.objects.create_user(username="other-quota-user")
        upload = self.create_upload()
        with self.assertRaises(QuotaStateError):
            reserve_upload_quota(upload.pk, other_user)

        upload.state = UploadSession.State.COMPLETED
        upload.save(update_fields=["state"])
        with self.assertRaises(QuotaStateError):
            reserve_upload_quota(upload.pk, self.user)

    def test_database_rejects_negative_quota_counters(self):
        with self.assertRaises(IntegrityError):
            with self.atomic():
                QuotaAccount.objects.filter(pk=self.account.pk).update(
                    reserved_bytes=-1
                )

    @patch("files.services._clone_encrypted_file")
    def test_copy_reserves_and_consumes_target_tenant_quota(self, clone_file):
        source = File.objects.create(
            tenant=self.tenant,
            owner=self.user,
            file_name="source.bin",
            file_size=40,
            file_path="uploads/source.enc",
        )
        clone_file.side_effect = lambda source_file, *, owner, folder, file_name, tenant: File.objects.create(
            tenant=tenant,
            owner=owner,
            folder=folder,
            file_name=file_name,
            file_size=source_file.file_size,
            file_path="uploads/copy.enc",
        )

        copied = clone_encrypted_file_with_quota(
            source,
            owner=self.user,
            folder=None,
            file_name="source (copy).bin",
            tenant=self.tenant,
        )

        self.account.refresh_from_db()
        upload = UploadSession.objects.get(file=copied)
        self.assertEqual(copied.tenant_id, self.tenant.pk)
        self.assertEqual(self.account.used_bytes, 40)
        self.assertEqual(self.account.reserved_bytes, 0)
        self.assertEqual(upload.state, UploadSession.State.COMPLETED)
        self.assertEqual(
            QuotaReservation.objects.get(upload_session=upload).state,
            QuotaReservation.State.CONSUMED,
        )

    @patch(
        "files.services._clone_encrypted_file",
        side_effect=ValueError("copy failed"),
    )
    def test_failed_copy_releases_reserved_quota(self, _clone_file):
        source = File.objects.create(
            tenant=self.tenant,
            owner=self.user,
            file_name="source.bin",
            file_size=40,
            file_path="uploads/source.enc",
        )

        with self.assertRaisesRegex(ValueError, "copy failed"):
            clone_encrypted_file_with_quota(
                source,
                owner=self.user,
                folder=None,
                file_name="source (copy).bin",
                tenant=self.tenant,
            )

        self.account.refresh_from_db()
        upload = UploadSession.objects.get(client_name="source (copy).bin")
        self.assertEqual(upload.state, UploadSession.State.FAILED)
        self.assertEqual(self.account.used_bytes, 0)
        self.assertEqual(self.account.reserved_bytes, 0)
        self.assertEqual(
            QuotaReservation.objects.get(upload_session=upload).state,
            QuotaReservation.State.RELEASED,
        )

    @staticmethod
    def atomic():
        from django.db import transaction

        return transaction.atomic()


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks.")
class QuotaReservationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_concurrent_reservations_cannot_overrun_quota(self):
        user = User.objects.create_user(username="concurrent-quota-user")
        tenant = user.personal_tenant
        account = QuotaAccount.objects.get(
            tenant=tenant,
            scope=QuotaAccount.Scope.TENANT,
        )
        account.limit_bytes = 100
        account.save(update_fields=["limit_bytes", "updated_at"])
        uploads = [
            UploadSession.objects.create(
                tenant=tenant,
                initiated_by=user,
                client_name=f"item-{index}.bin",
                expected_size_bytes=60,
                expires_at="2035-01-01T00:00:00Z",
            )
            for index in range(2)
        ]
        barrier = Barrier(2)

        def attempt(upload_id):
            from django.db import close_old_connections

            close_old_connections()
            try:
                barrier.wait()
                reserve_upload_quota(upload_id, User.objects.get(pk=user.pk))
                return "reserved"
            except QuotaExceeded:
                return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, [row.pk for row in uploads]))

        self.assertCountEqual(results, ["reserved", "rejected"])
        account.refresh_from_db()
        self.assertEqual(account.reserved_bytes, 60)
