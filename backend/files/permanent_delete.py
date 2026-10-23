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
        .select_related("storage_config")
        .order_by("created_at")
    )

    storage = None
    if any(location.state != StorageLocation.State.DELETED for location in locations):
        storage = get_storage_adapter()

    failures = []
    for location in locations:
        if location.state == StorageLocation.State.DELETED:
            continue
        location.state = StorageLocation.State.DELETE_PENDING
        location.save(update_fields=["state", "updated_at"])
        try:
            # S3 DeleteObject is idempotent; repeated attempts are safe.
            storage.delete_object(location.object_ref)
        except Exception:
            location.state = StorageLocation.State.ERROR
            location.save(update_fields=["state", "updated_at"])
            failures.append(location.object_ref)
        else:
            location.state = StorageLocation.State.DELETED
            location.save(update_fields=["state", "updated_at"])

    # If any MinIO operation failed, retain legacy media files as well. A retry
    # can safely skip object locations already marked DELETED and retry the rest.
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

        # Keep upload/quota history, but detach the protected FK to the deleted file.
        UploadSession.objects.filter(pk__in=session_ids).update(file=None)
        StorageLocation.objects.filter(file_version_id__in=version_ids).delete()
        FileVersion.objects.filter(pk__in=version_ids).delete()
        File.objects.filter(pk__in=file_ids).delete()

    return len(file_ids)
