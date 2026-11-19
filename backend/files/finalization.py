"""Verify an upload's content and publish it under the primary storage prefix.

The multipart worker provides a SHA-256-verified, seekable stream. It is
validated without materializing the entire file in RAM, then published with an
S3-side conditional copy. Legacy callers that supply raw bytes still use
PutObject, preserving their existing behavior.
"""
import hmac
import io
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files import File as DjangoFile
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from accounts.access import can_edit_workspace_content
from accounts.models import Membership, Tenant, Workspace, WorkspaceMembership
from files import cse
from files.models import File, FileVersion, StorageConfig, StorageLocation, UploadFinalizationJob, UploadSession
from files.quota import finalize_upload_quota
from files.services import unique_upload_name
from files.storage_adapters import get_storage_adapter
from files.storage_routing import adapter_for_upload, validate_upload_storage
from files.validators import MAX_UPLOAD_SIZE, calculate_sha256, detect_mime_type, validate_filename
from folders.models import Folder
from logs.models import ActivityLog
from logs.services import log_action
from sharing.services import can_edit_folder

logger = logging.getLogger(__name__)


class UploadDestinationUnavailable(ValidationError):
    """The upload's write permission was revoked before publication committed."""


class FinalizationClaimLost(Exception):
    """A newer worker owns this job; this attempt may not change its results."""


def lock_finalizing_upload(upload_id, job_attempt=None):
    """Lock session then job consistently; renew the claim at DB milestones."""
    session = UploadSession.objects.select_related("tenant", "target_folder").select_for_update(
        of=("self",),
    ).get(pk=upload_id)
    if job_attempt is not None:
        job = UploadFinalizationJob.objects.select_for_update().get(upload_session=session)
        if job.state != UploadFinalizationJob.State.PROCESSING or job.attempts != job_attempt:
            raise FinalizationClaimLost()
        job.save(update_fields=["updated_at"])
    return session


def _lock_writable_destination(session, actor):
    """Called with the session locked, only inside short database transactions."""
    workspace = Workspace.objects.select_for_update(no_key=True).get(pk=session.workspace_id)
    tenant = Tenant.objects.select_for_update(no_key=True).get(pk=session.tenant_id)
    # Lock the actual authorization rows so updates/revocation serialize with
    # publication. Never trust related objects cached before S3 I/O.
    membership = Membership.objects.select_for_update(no_key=True).filter(
        tenant=tenant, user_id=session.initiated_by_id,
    ).first()
    current_actor = get_user_model().objects.select_for_update(no_key=True).get(pk=session.initiated_by_id)
    if membership is not None:
        list(WorkspaceMembership.objects.select_for_update(no_key=True).filter(
            workspace=workspace, membership=membership,
        ))
    workspace.tenant = tenant
    session.workspace = workspace
    session.tenant = tenant
    if (
        getattr(actor, "pk", None) != current_actor.pk
        or workspace.tenant_id != tenant.pk
        or not can_edit_workspace_content(current_actor, workspace)
    ):
        raise UploadDestinationUnavailable("Upload destination is no longer writable.")
    if session.target_folder_id:
        # Refresh folder scope too; the selected destination may have moved or
        # entered Trash since this session was created.
        folder = Folder.objects.select_for_update(no_key=True).get(pk=session.target_folder_id)
        if (folder.tenant_id != tenant.pk or folder.workspace_id != workspace.pk
                or not can_edit_folder(folder, current_actor)):
            raise UploadDestinationUnavailable("Upload destination is no longer writable.")
        session.target_folder = folder
    validate_upload_storage(session, lock=True)
    if session.cse_metadata:
        cse.authorize_write(current_actor, tenant, workspace, session.target_folder, session.cse_metadata,
                            session.expected_size_bytes, session.expected_sha256, session.storage_connection, pinned=True)
    elif cse.requires_cse(tenant, workspace):
        raise UploadDestinationUnavailable("Destination requires a CSE upload.")


def _clean_published_staging(storage, upload_id, staging_key):
    try:
        # Một key đang có location phải đi qua quy trình permanent delete.
        if not StorageLocation.objects.filter(object_ref=staging_key).exists():
            storage.delete_object(staging_key)
    except Exception as error:
        logger.warning("Staging cleanup deferred: upload_id=%s error_type=%s", upload_id, type(error).__name__)


def finalize_verified_upload(
    session, plaintext, actor, *, verified_sha256=None, verified_etag="", job_attempt=None
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
    encrypted = bool(session.cse_metadata)
    if actual_size != session.expected_size_bytes or actual_size > (cse.MAX_WIRE if encrypted else MAX_UPLOAD_SIZE):
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
    logical_size = actual_size
    if encrypted:
        prefix = cse.authorize_write(actor, session.tenant, session.workspace, session.target_folder,
                                     session.cse_metadata, actual_size, actual_sha256,
                                     session.storage_connection, pinned=True)
        if content.read(cse.PREFIX) != prefix or verified_sha256 is None:
            raise ValidationError("Ciphertext prefix does not match the signed manifest.")
        content.seek(0)
        mime_type = "application/octet-stream"
        logical_size = session.cse_metadata["logical_size"]
    else:
        mime_type = detect_mime_type(DjangoFile(content, name=session.client_name), extension)
    scanner_path = getattr(settings, "SECUREDRIVE_UPLOAD_SCANNER", "")
    if scanner_path and not encrypted:
        with transaction.atomic():
            session = lock_finalizing_upload(session.pk, job_attempt)
            if session.state not in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
                raise ValueError("Upload state changed before scanning.")
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
            with transaction.atomic():
                session = lock_finalizing_upload(session.pk, job_attempt)
                if session.state not in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
                    raise ValueError("Upload state changed during scanning.")
                session.state = UploadSession.State.FAILED
                session.failure_code = "security_scan_rejected"
                session.save(update_fields=["state", "failure_code", "updated_at"])
                finalize_upload_quota(session.pk, completed=False)
            raise ValidationError("File did not pass the configured security scan.")

    storage = adapter_for_upload(session, fallback=get_storage_adapter)
    # Persist the destination key *before* performing network I/O. If Django
    # terminates after CopyObject but before the DB commit, the retry will use
    # the same key. Never hold a DB transaction open during the S3 operation.
    with transaction.atomic():
        locked_session = lock_finalizing_upload(session.pk, job_attempt)
        if locked_session.state in (UploadSession.State.AVAILABLE, UploadSession.State.COMPLETED):
            return {"upload_id": str(locked_session.pk), "state": locked_session.state, "file_id": locked_session.file_id}
        if locked_session.state not in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
            raise ValueError("Upload state changed during finalization.")
        _lock_writable_destination(locked_session, actor)
        final_key = locked_session.final_object_key or storage.create_object_key("primary")
        if not locked_session.final_object_key:
            locked_session.final_object_key = final_key
            locked_session.save(update_fields=["final_object_key", "updated_at"])
        session = locked_session

    if verified_sha256 is not None and session.object_key and actual_size > 0:
        # The worker read and SHA-256-verified the staged bytes. Copy within
        # storage without downloading/uploading them a second time.
        published = storage.publish_verified_object(
            session.object_key, final_key,
            expected_size=actual_size, expected_sha256=actual_sha256,
            upload_session_id=str(session.pk), content_type=mime_type,
            expected_source_etag=verified_etag,
        )
    else:
        # Legacy duplication has no staged object. Keep its verified PutObject
        # path but perform the network write outside this function's DB atomic.
        content.seek(0)
        published = storage.put_object(
            final_key, content, size_bytes=actual_size,
            sha256_hex=actual_sha256,
            content_type=mime_type or "application/octet-stream",
        )

    if encrypted and (not published.version_id or published.version_id == "null"):
        raise ValidationError("Encrypted object has no pinned provider version.")

    with transaction.atomic():
        locked = lock_finalizing_upload(session.pk, job_attempt)
        if locked.state in (UploadSession.State.AVAILABLE, UploadSession.State.COMPLETED):
            return {"upload_id": str(locked.pk), "state": locked.state, "file_id": locked.file_id}
        if locked.state not in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
            raise ValueError("Upload state changed during finalization.")
        _lock_writable_destination(locked, actor)
        tenant = locked.tenant
        folder = locked.target_folder
        owner = folder.owner if folder else actor
        visible_name = unique_upload_name(
            File, "file_name", locked.client_name,
            folder=folder, owner=owner, workspace=locked.workspace,
        )
        drive_file = File.objects.create(
            tenant=tenant, workspace=locked.workspace, owner=owner, folder=folder,
            file_name=visible_name, file_size=logical_size, mime_type=mime_type,
            hash_sha256=actual_sha256, is_encrypted=encrypted,
            encryption_version=1, file_path="",
        )
        if locked.storage_config_id:
            cfg = locked.storage_config
        else:
            cfg, _ = StorageConfig.objects.get_or_create(
                tenant=tenant, provider=StorageConfig.Provider.S3,
                defaults={'endpoint':settings.SECUREDRIVE_STORAGE_ENDPOINT_URL,'status':StorageConfig.Status.ACTIVE})
        version = FileVersion.objects.create(
            tenant=tenant, file=drive_file, version_number=1,
            state=FileVersion.State.AVAILABLE, size_bytes=logical_size,
            mime_type=mime_type, sha256=actual_sha256, is_current=True,
            is_encrypted=encrypted, encryption_scheme=cse.SCHEME if encrypted else "", encryption_version=1,
            cse_metadata=locked.cse_metadata, crypto_version_id=locked.crypto_version_id,
            verified_at=timezone.now(),
        )
        StorageLocation.objects.create(
            tenant=tenant, file_version=version, storage_config=cfg,
            storage_connection_id=locked.storage_connection_id,
            object_ref=final_key, state=StorageLocation.State.AVAILABLE,
            provider_version_id=published.version_id,
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
                "size_bytes": logical_size,
                "upload_id": str(locked.pk),
                "source": "cse_multipart" if encrypted else "multipart",
            },
        )

        if locked.object_key:
            transaction.on_commit(
                lambda: _clean_published_staging(storage, locked.pk, locked.object_key)
            )
    return {
        "upload_id": str(session.pk),
        "state": UploadSession.State.AVAILABLE,
        "file_id": drive_file.pk,
        "name": visible_name,
    }
