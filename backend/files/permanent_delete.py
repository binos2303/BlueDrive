"""Safe physical cleanup for permanently deleted Drive files.

Object storage operations happen before deleting database metadata. If a storage
operation fails, metadata is retained and locations record the failure so the
operation can be retried without silently orphaning an object.
"""
from collections import defaultdict

from django.db import transaction

from accounts.models import QuotaAccount
from files.models import (
    File,
    FileVersion,
    QuotaReservation,
    StorageLocation,
    UploadSession,
)
from files.storage_adapters import get_storage_adapter
from files.storage_routing import adapter_for_location


class PermanentDeleteError(Exception):
    """Raised when not all underlying objects could be removed."""


def permanently_delete_files(files):
    files = list(files)
    if not files:
        return 0

    file_ids = [item.pk for item in files]
    versions = list(FileVersion.objects.filter(file_id__in=file_ids))
    version_ids = [item.pk for item in versions]
    locations = list(
        StorageLocation.objects.filter(file_version_id__in=version_ids)
        .select_related("storage_config", "storage_connection__cluster", "tenant")
        .order_by("created_at")
    )

    adapters = {}

    failures = []
    for location in locations:
        if location.state == StorageLocation.State.DELETED:
            continue
        location.state = StorageLocation.State.DELETE_PENDING
        location.save(update_fields=["state", "updated_at"])
        try:
            target = (location.storage_connection_id, location.storage_config_id if not location.storage_connection_id else None)
            if target not in adapters:
                adapters[target] = adapter_for_location(location,fallback=get_storage_adapter,cleanup=True)
            storage = adapters[target]
            # S3 DeleteObject is idempotent; repeated attempts are safe.
            storage.delete_object(location.object_ref)
        except Exception:
            location.state = StorageLocation.State.ERROR
            location.save(update_fields=["state", "updated_at"])
            failures.append(location.object_ref)
        else:
            location.state = StorageLocation.State.DELETED
            location.save(update_fields=["state", "updated_at"])

    # Giữ media legacy khi S3 lỗi; lần thử lại bỏ qua location đã xóa thành công.
    if failures:
        raise PermanentDeleteError(
            f"Could not permanently delete {len(failures)} storage object(s)."
        )

    # Support legacy objects stored by Django's configured MEDIA storage.
    for drive_file in files:
        if not drive_file.file_path:
            continue
        try:
            drive_file.file_path.delete(save=False)
        except Exception:
            failures.append(f"media:{drive_file.pk}")

    if failures:
        raise PermanentDeleteError(
            f"Could not permanently delete {len(failures)} legacy media object(s)."
        )

    with transaction.atomic():
        sessions = list(
            UploadSession.objects.select_for_update()
            .filter(file_id__in=file_ids)
            .order_by("pk")
        )
        session_ids = [session.pk for session in sessions]
        reservations = list(
            QuotaReservation.objects.select_for_update()
            .filter(
                upload_session_id__in=session_ids,
                state=QuotaReservation.State.CONSUMED,
            )
            .order_by("quota_account_id", "pk")
        )
        actual_sizes = {
            session.pk: (
                session.actual_size_bytes
                if session.actual_size_bytes is not None
                else next((f.file_size for f in files if f.pk == session.file_id), 0)
            )
            for session in sessions
        }
        decrement_by_account = defaultdict(int)
        for reservation in reservations:
            decrement_by_account[reservation.quota_account_id] += max(
                0, int(actual_sizes.get(reservation.upload_session_id, 0))
            )

        # Legacy files imported before UploadSession bookkeeping may have no
        # consumed reservation. The reconciliation command includes those
        # logical bytes, so release them on physical deletion as well.
        billed_files = {
            session.file_id for session in sessions
            if any(res.upload_session_id == session.pk for res in reservations)
        }
        for file in files:
            if file.pk in billed_files:
                continue
            if file.workspace and not file.workspace.is_my_drive:
                quotas = QuotaAccount.objects.filter(
                    workspace_id=file.workspace_id, scope=QuotaAccount.Scope.WORKSPACE,
                )
            else:
                quotas = QuotaAccount.objects.filter(
                    tenant_id=file.tenant_id, scope=QuotaAccount.Scope.TENANT,
                )
                if file.workspace and file.workspace.owned_identity_id is not None:
                    # My Drive employee được tính cả ngân sách Organization và cá nhân.
                    quotas = quotas | QuotaAccount.objects.filter(
                        tenant_id=file.tenant_id, user_id=file.owner_id,
                        scope=QuotaAccount.Scope.MEMBER,
                    )
            for quota in quotas:
                decrement_by_account[quota.pk] += max(0, int(file.file_size))

        accounts = {
            account.pk: account
            for account in QuotaAccount.objects.select_for_update()
            .filter(pk__in=decrement_by_account.keys())
            .order_by("pk")
        }
        for account_id, amount in decrement_by_account.items():
            account = accounts[account_id]
            account.used_bytes = max(0, account.used_bytes - amount)
            account.save(update_fields=["used_bytes", "updated_at"])

        StorageLocation.objects.filter(file_version_id__in=version_ids).delete()
        FileVersion.objects.filter(pk__in=version_ids).delete()
        # Chỉ gỡ FK sau khi xóa metadata phiên bản; giữ nguyên lịch sử upload/quota thành công.
        UploadSession.objects.filter(pk__in=session_ids).update(file=None)
        File.objects.filter(pk__in=file_ids).delete()

    return len(file_ids)
