import hashlib
import tempfile

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db import IntegrityError, OperationalError
from django.utils import timezone

from files.finalization import (
    FinalizationClaimLost, UploadDestinationUnavailable,
    finalize_verified_upload, lock_finalizing_upload,
)
from files.models import StorageLocation, UploadFinalizationJob, UploadSession
from files.quota import QuotaStateError, finalize_upload_quota
from files.storage_adapters import get_storage_adapter
from files.storage_routing import adapter_for_upload
from files.storage_adapters.base import (
    MultipartPart,
    StorageError,
    StorageIntegrityError,
    StorageNotFoundError,
    StorageRetryableError,
)
from files.validators import MAX_UPLOAD_SIZE, calculate_sha256
from files.cse import MAX_WIRE
import logging

logger = logging.getLogger(__name__)


PART_SIZE = 8 * 1024 * 1024
MAX_ATTEMPTS = 3


def _quarantine_failed_upload(upload_id):
    """Move a completed but permanently failed staging object to quarantine.

    Uses a deterministic key so the operation can be retried after a process crash.
    It does not delete a staging object until the adapter has verified its copy.
    If multipart completion never produced an object, it aborts the multipart upload.
    """
    session = UploadSession.objects.filter(pk=upload_id).first()
    if session is None or session.state != UploadSession.State.FAILED or not session.object_key:
        return False

    # Already quarantined (including legacy sessions created by older code).
    if session.object_key.startswith("quarantine/"):
        return True

    storage = adapter_for_upload(session, fallback=get_storage_adapter, cleanup=True)
    quarantine_key = f"quarantine/{session.pk.hex}"
    if StorageLocation.objects.filter(
        object_ref__in={session.object_key, session.final_object_key, quarantine_key} - {""},
    ).exists():
        return False

    # If finalization wrote PRIMARY but the database transaction did not commit,
    # that object is an orphan. Remove it best-effort; the staging source remains
    # the canonical input for quarantine.
    if session.final_object_key:
        try:
            storage.delete_object(session.final_object_key)
        except StorageNotFoundError:
            pass
        except StorageError as error:
            logger.warning(
                "Orphaned publication cleanup deferred: upload_id=%s error_type=%s",
                session.pk, type(error).__name__,
            )

    try:
        stat = storage.stat_object(session.object_key)
    except StorageNotFoundError:
        # Recovery case: a previous invocation may have copied to quarantine but
        # failed before updating PostgreSQL.
        try:
            storage.stat_object(quarantine_key)
        except StorageNotFoundError:
            if session.provider_upload_id:
                try:
                    storage.abort_multipart(session.object_key, session.provider_upload_id)
                except StorageError as error:
                    logger.warning(
                        "Incomplete multipart abort deferred: upload_id=%s error_type=%s",
                        session.pk, type(error).__name__,
                    )
            return False
        else:
            UploadSession.objects.filter(
                pk=session.pk, state=UploadSession.State.FAILED
            ).update(object_key=quarantine_key)
            return True

    storage.quarantine_object(
        session.object_key,
        quarantine_key=quarantine_key,
        expected_size=stat.size_bytes,
    )
    updated = UploadSession.objects.filter(
        pk=session.pk, state=UploadSession.State.FAILED
    ).update(object_key=quarantine_key)
    if not updated:
        logger.warning(
            "Quarantined upload object but could not update its session reference: %s",
            session.pk,
        )
        return False
    return True


def _mark_failed(upload, job, code):
    if upload.state in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
        upload.state = UploadSession.State.FAILED
        upload.failure_code = code
        upload.save(update_fields=["state", "failure_code", "updated_at"])
    try:
        finalize_upload_quota(upload.pk, completed=False)
    except QuotaStateError:
        logger.warning("Terminal upload quota requires reconciliation: upload_id=%s", upload.pk)
    job.state = UploadFinalizationJob.State.FAILED
    job.save(update_fields=["state", "updated_at"])


def _try_quarantine(upload_id):
    try:
        if not _quarantine_failed_upload(upload_id):
            logger.warning("Failed upload requires cleanup review: upload_id=%s", upload_id)
    except Exception as error:
        logger.warning("Quarantine deferred: upload_id=%s error_type=%s", upload_id, type(error).__name__)


class Command(BaseCommand):
    help = "Verify and optionally scan staged uploads, publish valid files to PRIMARY, and quarantine permanent failures."

    def handle(self, *args, **options):
        # Recover the DB/storage split if multipart completion succeeded but the
        # web request died before committing its outbox row.
        for upload_id in UploadSession.objects.filter(
            state__in=[UploadSession.State.VERIFYING, UploadSession.State.SCANNING]
        ).values_list("pk", flat=True).iterator():
            UploadFinalizationJob.objects.get_or_create(upload_session_id=upload_id)
        stale_before = timezone.now() - UploadFinalizationJob.STALE_AFTER
        UploadFinalizationJob.objects.filter(
            state=UploadFinalizationJob.State.PROCESSING, updated_at__lt=stale_before
        ).update(state=UploadFinalizationJob.State.PENDING)
        done = failed = retrying = 0
        for job_id, upload_id in UploadFinalizationJob.objects.filter(
            state=UploadFinalizationJob.State.PENDING
        ).order_by("pk").values_list("pk", "upload_session_id")[:100]:
            with transaction.atomic():
                # Session -> job is also the publication/failure lock order.
                upload = UploadSession.objects.select_for_update().get(pk=upload_id)
                job = UploadFinalizationJob.objects.select_for_update().get(pk=job_id)
                if job.state != UploadFinalizationJob.State.PENDING:
                    continue
                if upload.state in (UploadSession.State.AVAILABLE, UploadSession.State.COMPLETED):
                    job.state = UploadFinalizationJob.State.DONE
                    job.save(update_fields=["state", "updated_at"])
                    done += 1
                    continue
                if upload.state not in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
                    if upload.state in (UploadSession.State.FAILED, UploadSession.State.CANCELED, UploadSession.State.EXPIRED):
                        try:
                            finalize_upload_quota(upload.pk, completed=False)
                        except QuotaStateError:
                            logger.warning("Terminal upload quota requires reconciliation: upload_id=%s", upload.pk)
                    job.state = UploadFinalizationJob.State.FAILED
                    job.save(update_fields=["state", "updated_at"])
                    failed += 1
                    continue
                exhausted = job.attempts >= MAX_ATTEMPTS
                if exhausted:
                    # Reclaim lần cuối bị crash không cấp thêm một lượt RPC.
                    _mark_failed(upload, job, "finalization_failed")
                    failed += 1
                else:
                    job.state = UploadFinalizationJob.State.PROCESSING
                    job.attempts += 1
                    job.save(update_fields=["state", "attempts", "updated_at"])
            if exhausted:
                _try_quarantine(upload.pk)
                continue
            try:
                storage = adapter_for_upload(upload, fallback=get_storage_adapter)
                if upload.expected_size_bytes:
                    parts = [MultipartPart(part_number=int(part["part_number"]), etag=str(part["etag"])) for part in upload.part_manifest]
                    stat = storage.complete_multipart(
                        upload.object_key, upload.provider_upload_id, parts,
                        expected_size=upload.expected_size_bytes,
                        expected_part_size=PART_SIZE,
                        expected_part_count=(upload.expected_size_bytes + PART_SIZE - 1) // PART_SIZE,
                        expected_upload_session_id=str(upload.pk),
                    )
                    if stat.metadata.get("securedrive-upload-id") != str(upload.pk):
                        raise StorageIntegrityError("Completed object metadata failed verification.")
                else:
                    stat = storage.verify_object(
                        upload.object_key, expected_size=0,
                        expected_sha256=hashlib.sha256(b"").hexdigest(),
                    )
                limit = MAX_WIRE if upload.cse_metadata else MAX_UPLOAD_SIZE
                if stat.size_bytes != upload.expected_size_bytes or stat.size_bytes > limit:
                    raise StorageIntegrityError("Completed object size failed verification.")
                # Download to an 8-MiB memory-bounded spool instead of holding
                # the entire 100-MiB object in RAM. The verified bytes are used
                # for MIME/ZIP checks and (optionally) a scanner. On success, S3
                # copies the original object internally, avoiding a second upload
                # from Django. The original staging key remains until DB commit.
                with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as verified:
                    retrieved = storage.download_to(
                        upload.object_key, verified, max_bytes=limit
                    )
                    if retrieved.size_bytes != stat.size_bytes:
                        raise StorageIntegrityError("Staging object size changed during verification.")
                    if stat.etag and retrieved.etag != stat.etag:
                        raise StorageIntegrityError("Staging object changed during verification.")
                    verified.seek(0, 2)
                    actual_size = verified.tell()
                    if actual_size != upload.expected_size_bytes:
                        raise StorageIntegrityError("Verified object size changed during finalization.")
                    digest = calculate_sha256(verified)
                    if upload.expected_sha256 and digest != upload.expected_sha256:
                        raise StorageIntegrityError("Verified object checksum changed during finalization.")
                    with transaction.atomic():
                        current = lock_finalizing_upload(upload.pk, job.attempts)
                        if current.state not in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
                            raise ValueError("Upload state changed during verification.")
                        current.received_bytes = current.actual_size_bytes = actual_size
                        current.save(update_fields=["received_bytes", "actual_size_bytes", "updated_at"])
                    finalize_verified_upload(
                        upload, verified, upload.initiated_by,
                        verified_sha256=digest, verified_etag=retrieved.etag, job_attempt=job.attempts,
                    )
                done += UploadFinalizationJob.objects.filter(
                    pk=job.pk, state=UploadFinalizationJob.State.PROCESSING, attempts=job.attempts,
                ).update(state=UploadFinalizationJob.State.DONE, updated_at=timezone.now())
            except FinalizationClaimLost:
                logger.info("Upload finalization claim superseded: upload_id=%s, attempt=%s", upload.pk, job.attempts)
            except Exception as error:
                with transaction.atomic():
                    current = UploadSession.objects.select_for_update().get(pk=upload.pk)
                    current_job = UploadFinalizationJob.objects.select_for_update().get(pk=job.pk)
                    if current_job.state != UploadFinalizationJob.State.PROCESSING or current_job.attempts != job.attempts:
                        continue
                    if current.state in (UploadSession.State.AVAILABLE, UploadSession.State.COMPLETED):
                        current_job.state = UploadFinalizationJob.State.DONE
                        current_job.save(update_fields=["state", "updated_at"])
                        done += 1
                        continue
                    # Serialization/connection errors có thể chỉ xuất hiện lúc COMMIT.
                    transient = isinstance(error, (StorageRetryableError, IntegrityError, OperationalError))
                    if transient and job.attempts < MAX_ATTEMPTS and current.state in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
                        current_job.state = UploadFinalizationJob.State.PENDING
                        current_job.save(update_fields=["state", "updated_at"])
                        retrying += 1
                    else:
                        _mark_failed(current, current_job,
                            "destination_not_writable" if isinstance(error, UploadDestinationUnavailable) else "finalization_failed")
                        failed += 1
                logger.error(
                    "Upload finalization failed: upload_id=%s, job_id=%s, "
                    "attempt=%s, error_type=%s",
                    upload.pk,
                    job.pk,
                    job.attempts,
                    type(error).__name__,
                )
                if current_job.state == UploadFinalizationJob.State.FAILED:
                    _try_quarantine(upload.pk)
        self.stdout.write(f"Finalized: {done}; retrying: {retrying}; failed: {failed}")
