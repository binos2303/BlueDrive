"""Verify an upload's content and publish it under the primary storage prefix.

The multipart worker provides a SHA-256-verified, seekable stream. It is
validated without materializing the entire file in RAM, then published with an
S3-side conditional copy. Legacy callers that supply raw bytes still use
PutObject, preserving their existing behavior.
"""
import hashlib
import hmac
import io

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files import File as DjangoFile
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from files.models import File, FileVersion, StorageConfig, StorageLocation, UploadSession
from files.quota import finalize_upload_quota
from files.services import unique_upload_name
from files.storage_adapters import get_storage_adapter
from files.validators import MAX_UPLOAD_SIZE, calculate_sha256, detect_mime_type, validate_filename
from logs.models import ActivityLog
from logs.services import log_action


def finalize_verified_upload(
    session, plaintext, actor, *, verified_sha256=None, verified_etag=""
):
    """Publish a verified upload. `verified_sha256` is trusted only from the worker.

    For direct byte callers (e.g. duplication) this function hashes the bytes
    itself. For the multipart worker, the content has already been hashed from
    the downloaded staging object, so the stream is not hashed a second time.
    """
    session.refresh_from_db()
    if session.state in (UploadSession.State.AVAILABLE, UploadSession.State.COMPLETED):
        return {"upload_id": str(session.pk), "state": session.state, "file_id": session.file_id}
    if session.state not in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
        raise ValueError("Upload is not awaiting finalization.")

    content = io.BytesIO(plaintext) if isinstance(plaintext, bytes) else plaintext
    if not all(callable(getattr(content, name, None)) for name in ("read", "seek", "tell")):
        raise TypeError("Verified upload content must be bytes or a seekable binary stream.")
    content.seek(0, io.SEEK_END)
    actual_size = content.tell()
    content.seek(0)
    if actual_size != session.expected_size_bytes or actual_size > MAX_UPLOAD_SIZE:
        raise ValueError("Verified upload size does not match its reservation.")
    actual_sha256 = verified_sha256 or calculate_sha256(content)
    if not isinstance(actual_sha256, str) or len(actual_sha256) != 64 or any(
        char not in "0123456789abcdefABCDEF" for char in actual_sha256
    ):
        raise ValueError("Verified upload SHA-256 is malformed.")
    actual_sha256 = actual_sha256.lower()
    if session.expected_sha256 and not hmac.compare_digest(
        actual_sha256, session.expected_sha256.lower()
    ):
        raise ValueError("Verified upload checksum does not match its reservation.")

    extension = validate_filename(session.client_name)
    mime_type = detect_mime_type(DjangoFile(content, name=session.client_name), extension)
    scanner_path = getattr(settings, "SECUREDRIVE_UPLOAD_SCANNER", "")
    if scanner_path:
        session.state = UploadSession.State.SCANNING
        session.save(update_fields=["state", "updated_at"])
        # Existing scanner hook accepts bytes. Its 100-MiB buffer is retained
        # only when configured; replace with a stream-based scanner interface
        # when the malware scanning stage is implemented.
        content.seek(0)
        scanner_payload = content.read(MAX_UPLOAD_SIZE + 1)
        content.seek(0)
        if len(scanner_payload) != actual_size or import_string(scanner_path)(
            scanner_payload, session.client_name
        ) is not True:
            session.state = UploadSession.State.FAILED
            session.failure_code = "security_scan_rejected"
            session.save(update_fields=["state", "failure_code", "updated_at"])
            finalize_upload_quota(session.pk, completed=False, actor=actor)
            raise ValidationError("File did not pass the configured security scan.")

    storage = get_storage_adapter()
    # Persist the destination key *before* performing network I/O. If Django
    # terminates after CopyObject but before the DB commit, the retry will use
    # the same key. Never hold a DB transaction open during the S3 operation.
    with transaction.atomic():
        locked_session = UploadSession.objects.select_for_update().get(pk=session.pk)
        if locked_session.state in (UploadSession.State.AVAILABLE, UploadSession.State.COMPLETED):
            return {"upload_id": str(locked_session.pk), "state": locked_session.state, "file_id": locked_session.file_id}
        if locked_session.state not in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
            raise ValueError("Upload state changed during finalization.")
        final_key = locked_session.final_object_key or storage.create_object_key("primary")
        if not locked_session.final_object_key:
            locked_session.final_object_key = final_key
            locked_session.save(update_fields=["final_object_key", "updated_at"])
        session = locked_session

    if verified_sha256 is not None and session.object_key and actual_size > 0:
        # The worker read and SHA-256-verified the staged bytes. Copy within
        # storage without downloading/uploading them a second time.
        storage.publish_verified_object(
            session.object_key, final_key,
            expected_size=actual_size, expected_sha256=actual_sha256,
            upload_session_id=str(session.pk), content_type=mime_type,
            expected_source_etag=verified_etag,
        )
    else:
        # Legacy duplication has no staged object. Keep its verified PutObject
        # path but perform the network write outside this function's DB atomic.
        content.seek(0)
        storage.put_object(
            final_key, content, size_bytes=actual_size,
            sha256_hex=actual_sha256,
            content_type=mime_type or "application/octet-stream",
        )

    tenant = session.tenant
    folder = session.target_folder
    owner = folder.owner if folder else actor
    with transaction.atomic():
        locked = (
            UploadSession.objects
            .select_related("tenant", "target_folder")
            .select_for_update(of=("self",))
            .get(pk=session.pk)
        )
        if locked.state in (UploadSession.State.AVAILABLE, UploadSession.State.COMPLETED):
            return {"upload_id": str(locked.pk), "state": locked.state, "file_id": locked.file_id}
        if locked.state not in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
            raise ValueError("Upload state changed during finalization.")
        visible_name = unique_upload_name(
            File, "file_name", locked.client_name,
            folder=folder, owner=owner, workspace=locked.workspace,
        )
        drive_file = File.objects.create(
            tenant=tenant, workspace=locked.workspace, owner=owner, folder=folder,
            file_name=visible_name, file_size=actual_size, mime_type=mime_type,
            hash_sha256=actual_sha256, is_encrypted=False,
            encryption_version=1, file_path="",
        )
        cfg, _ = StorageConfig.objects.get_or_create(
            tenant=tenant, provider=StorageConfig.Provider.MINIO,
            defaults={
                "endpoint": settings.SECUREDRIVE_STORAGE_ENDPOINT_URL,
                "status": StorageConfig.Status.ACTIVE,
            },
        )
        version = FileVersion.objects.create(
            tenant=tenant, file=drive_file, version_number=1,
            state=FileVersion.State.AVAILABLE, size_bytes=actual_size,
            mime_type=mime_type, sha256=actual_sha256, is_current=True,
            is_encrypted=False, encryption_scheme="", encryption_version=1,
            verified_at=timezone.now(),
        )
        StorageLocation.objects.create(
            tenant=tenant, file_version=version, storage_config=cfg,
            object_ref=final_key, state=StorageLocation.State.AVAILABLE,
            size_bytes=actual_size, checksum=actual_sha256,
            verified_at=timezone.now(),
        )
        locked.file = drive_file
        locked.state = UploadSession.State.AVAILABLE
        locked.completed_at = timezone.now()
        locked.save(update_fields=["file", "state", "completed_at", "updated_at"])
        finalize_upload_quota(
            locked.pk, completed=True, actual_size_bytes=actual_size, actor=actor
        )
        log_action(
            locked.initiated_by,
            ActivityLog.Action.UPLOAD,
            f"Uploaded {drive_file.file_name}",
            obj=drive_file,
            metadata={
                "size_bytes": actual_size,
                "upload_id": str(locked.pk),
                "source": "multipart",
            },
        )

    if session.object_key:
        try:
            storage.delete_object(session.object_key)
        except Exception:
            # Reconciliation can garbage-collect the source when it is safe.
            pass
    return {
        "upload_id": str(session.pk),
        "state": UploadSession.State.AVAILABLE,
        "file_id": drive_file.pk,
        "name": visible_name,
    }
