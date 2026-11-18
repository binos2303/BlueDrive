"""Safe physical cleanup for permanently deleted Drive files.

Object storage operations happen before deleting database metadata. If a storage
operation fails, metadata is retained and locations record the failure so the
operation can be retried without silently orphaning an object.
"""
from collections import defaultdict

from django.db import DatabaseError, transaction
from django.utils import timezone

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
from folders.models import Folder


class PermanentDeleteError(Exception):
    """Raised when not all underlying objects could be removed."""


class FilePurgeInProgress(Exception):
    """Một file đã bắt đầu xóa vật lý nên không thể trả lại từ Trash."""


@transaction.atomic
def restore_trashed_files(queryset):
    files = list(queryset.filter(deleted_at__isnull=False)
                 .select_for_update(of=("self",), no_key=True).order_by("pk"))
    if any(file.purge_started_at for file in files):
        raise FilePurgeInProgress()
    return File.objects.filter(pk__in=[file.pk for file in files]).update(deleted_at=None)


def _lock_purge_roots(root_ids):
    roots = Folder.objects.filter(pk__in=root_ids).select_for_update().order_by("pk")
    if any(folder.deleted_at is None for folder in roots):
        raise PermanentDeleteError("Folder was restored during deletion.")


def finish_folder_purge(folders, root_ids=()):
    folder_ids = [folder.pk for folder in folders.select_for_update().order_by("pk")]
    _lock_purge_roots(root_ids)
    # Chặn cascade sang nội dung mới hoặc ngoài tập đã kiểm quyền và xóa bytes.
    if (File.objects.filter(folder_id__in=folder_ids).exists()
            or Folder.objects.filter(parent_id__in=folder_ids).exclude(pk__in=folder_ids).exists()):
        raise PermanentDeleteError("Folder content changed during deletion.")
    terminal = (
        UploadSession.State.COMPLETED, UploadSession.State.FAILED,
        UploadSession.State.CANCELED, UploadSession.State.EXPIRED,
    )
    sessions = UploadSession.objects.filter(target_folder_id__in=folder_ids)
    if sessions.exclude(state__in=terminal).exists():
        raise PermanentDeleteError("Folder still has an active upload.")
    sessions.filter(state__in=terminal).update(target_folder=None)
    Folder.objects.filter(pk__in=folder_ids).delete()
    return len(folder_ids)


@transaction.atomic
def _begin_purge(snapshots, root_ids):
    files = list(File.objects.select_for_update(no_key=True)
                 .filter(pk__in=snapshots).order_by("pk"))
    _lock_purge_roots(root_ids)
    now = timezone.now()
    for current in files:
        selected = snapshots[current.pk]
        if (current.tenant_id, current.workspace_id, current.folder_id, current.owner_id, current.file_name) != (
            selected.tenant_id, selected.workspace_id, selected.folder_id, selected.owner_id, selected.file_name,
        ) or (current.purge_started_at is None and current.deleted_at != selected.deleted_at):
            raise PermanentDeleteError("File changed before permanent deletion.")
        if current.purge_started_at is None:
            current.purge_started_at = now
            current.deleted_at = current.deleted_at or now
            current.save(update_fields=["purge_started_at", "deleted_at", "updated_at"])
    # Ngừng cấp bytes mới trước khi xóa version vật lý, kể cả khi DB commit cuối thất bại.
    FileVersion.objects.filter(file_id__in=[file.pk for file in files]).update(state=FileVersion.State.DELETING)
    return files


def permanently_delete_files(files, *, on_deleted=None, trashed_folder_ids=()):
    snapshots = {file.pk: file for file in files}
    try:
        files = _begin_purge(snapshots, trashed_folder_ids)
    except DatabaseError as error:
        raise PermanentDeleteError("Could not record permanent deletion.") from error
    if not files:
        if not snapshots and on_deleted is not None:
            with transaction.atomic():
                on_deleted([])
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
        pending = StorageLocation.objects.filter(pk=location.pk).exclude(state=StorageLocation.State.DELETED)
        if not pending.update(state=StorageLocation.State.DELETE_PENDING, updated_at=timezone.now()):
            continue
        try:
            if StorageLocation.objects.filter(object_ref=location.object_ref).exclude(
                file_version__file_id__in=file_ids,
            ).exists():
                raise PermanentDeleteError("Object is still referenced by another file.")
            target = (location.storage_connection_id, location.storage_config_id if not location.storage_connection_id else None)
            if target not in adapters:
                adapters[target] = adapter_for_location(location, fallback=get_storage_adapter, cleanup=True)
            storage = adapters[target]
            # S3 DeleteObject is idempotent; repeated attempts are safe.
            storage.delete_object(location.object_ref)
        except Exception:
            if pending.update(state=StorageLocation.State.ERROR, updated_at=timezone.now()):
                failures.append(location.pk)
        else:
            pending.update(state=StorageLocation.State.DELETED, updated_at=timezone.now())

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
            if File.objects.filter(file_path=drive_file.file_path.name).exclude(pk__in=file_ids).exists():
                raise PermanentDeleteError("Legacy media is still referenced by another file.")
            drive_file.file_path.delete(save=False)
        except Exception:
            failures.append(f"media:{drive_file.pk}")

    if failures:
        raise PermanentDeleteError(
            f"Could not permanently delete {len(failures)} legacy media object(s)."
        )

    try:
        return _finish_purge(file_ids, on_deleted)
    except DatabaseError as error:
        raise PermanentDeleteError("Could not commit permanent deletion. Retry the same files.") from error


@transaction.atomic
def _finish_purge(file_ids, on_deleted):
    # Request thứ hai có thể hoàn tất RPC sau request đầu. Chỉ tính quota cho
    # các hàng File vẫn tồn tại sau khi giành lock, kể cả file legacy.
    files = list(File.objects.filter(pk__in=file_ids).select_for_update(no_key=True).order_by("pk"))
    if not files:
        return 0
    file_ids = [file.pk for file in files]
    versions = FileVersion.objects.filter(file_id__in=file_ids)
    locations = StorageLocation.objects.filter(file_version__in=versions)
    if locations.exclude(state=StorageLocation.State.DELETED).exists():
        raise PermanentDeleteError("Storage deletion has not been confirmed.")
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

    locations.delete()
    versions.delete()
    # Chỉ gỡ FK sau khi xóa metadata phiên bản; giữ nguyên lịch sử upload/quota thành công.
    UploadSession.objects.filter(pk__in=session_ids).update(file=None)
    File.objects.filter(pk__in=file_ids).delete()
    if on_deleted is not None:
        on_deleted(files)
    return len(file_ids)
