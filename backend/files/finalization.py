"""Validate a staged upload and publish its original bytes under the primary prefix."""
import hashlib
import io

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from files.models import File, FileVersion, StorageConfig, StorageLocation, UploadSession
from files.quota import finalize_upload_quota
from files.services import unique_upload_name
from files.storage_adapters import get_storage_adapter
from files.validators import detect_mime_type, validate_filename


def finalize_verified_upload(session, plaintext, actor):
    session.refresh_from_db()
    if session.state in (UploadSession.State.AVAILABLE, UploadSession.State.COMPLETED):
        return {"upload_id": str(session.pk), "state": session.state, "file_id": session.file_id}
    if session.state not in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
        raise ValueError("Upload is not awaiting finalization.")

    extension = validate_filename(session.client_name)
    mime_type = detect_mime_type(SimpleUploadedFile(session.client_name, plaintext), extension)
    scanner_path = getattr(settings, "SECUREDRIVE_UPLOAD_SCANNER", "")
    if scanner_path:
        session.state = UploadSession.State.SCANNING
        session.save(update_fields=["state", "updated_at"])
        if import_string(scanner_path)(plaintext, session.client_name) is not True:
            session.state = UploadSession.State.FAILED
            session.failure_code = "security_scan_rejected"
            session.save(update_fields=["state", "failure_code", "updated_at"])
            finalize_upload_quota(session.pk, completed=False, actor=actor)
            raise ValidationError("File did not pass the configured security scan.")

    storage = get_storage_adapter()
    # Reserve a stable primary key under a row lock before the external write.
    # Retries after a process crash use this exact key and can reconcile it.
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

    tenant = session.tenant
    folder = session.target_folder
    owner = folder.owner if folder else actor
    actual_sha256 = hashlib.sha256(plaintext).hexdigest()
    ciphertext_sha256 = ""
    visible_name = ""
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
        visible_name = unique_upload_name(File, "file_name", locked.client_name, folder=folder, owner=owner, workspace=locked.workspace)
        # Encryption is intentionally deferred for this MVP phase. The browser has
        # already uploaded the original chunks to STAGING; after server-side size,
        # checksum, MIME and optional scanner validation, publish the same plaintext
        # bytes to PRIMARY. Keep the encryption metadata empty so download can make
        # an explicit decision based on FileVersion.is_encrypted.
        drive_file = File.objects.create(
            tenant=tenant, workspace=locked.workspace, owner=owner, folder=folder, file_name=visible_name,
            file_size=len(plaintext), mime_type=mime_type, hash_sha256=actual_sha256,
            is_encrypted=False, encryption_version=1, file_path="",
        )
        ciphertext_sha256 = actual_sha256
        # PutObject verifies object size and SHA-256 before publishing to PRIMARY.
        storage.put_object(
            final_key,
            io.BytesIO(plaintext),
            size_bytes=len(plaintext),
            sha256_hex=actual_sha256,
            content_type=mime_type or "application/octet-stream",
        )
        cfg, _ = StorageConfig.objects.get_or_create(
            tenant=tenant, provider=StorageConfig.Provider.MINIO,
            defaults={"endpoint": settings.SECUREDRIVE_STORAGE_ENDPOINT_URL, "status": StorageConfig.Status.ACTIVE},
        )
        version = FileVersion.objects.create(
            tenant=tenant, file=drive_file, version_number=1,
            state=FileVersion.State.AVAILABLE, size_bytes=len(plaintext),
            mime_type=mime_type, sha256=actual_sha256, is_current=True,
            is_encrypted=False, encryption_scheme="", encryption_version=1,
            verified_at=timezone.now(),
        )
        StorageLocation.objects.create(
            tenant=tenant, file_version=version, storage_config=cfg,
            object_ref=final_key, state=StorageLocation.State.AVAILABLE,
            size_bytes=len(plaintext), checksum=ciphertext_sha256, verified_at=timezone.now(),
        )
        locked.file = drive_file
        locked.state = UploadSession.State.AVAILABLE
        locked.completed_at = timezone.now()
        locked.save(update_fields=["file", "state", "completed_at", "updated_at"])
        finalize_upload_quota(locked.pk, completed=True, actual_size_bytes=len(plaintext), actor=actor)

    try:
        storage.delete_object(session.object_key)
    except Exception:
        # The cleanup command can remove the staged object after session expiry.
        pass
    return {"upload_id": str(session.pk), "state": UploadSession.State.AVAILABLE, "file_id": drive_file.pk, "name": visible_name}
