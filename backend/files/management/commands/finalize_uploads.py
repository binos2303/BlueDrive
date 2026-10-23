import hashlib
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db import IntegrityError
from django.utils import timezone

from files.finalization import finalize_verified_upload
from files.models import UploadFinalizationJob, UploadSession
from files.quota import finalize_upload_quota
from files.storage_adapters import get_storage_adapter
from files.storage_adapters.base import (
    MultipartPart,
    StorageError,
    StorageIntegrityError,
    StorageNotFoundError,
    StorageRetryableError,
)
from files.validators import MAX_UPLOAD_SIZE
import logging

logger = logging.getLogger(__name__)


PART_SIZE = 8 * 1024 * 1024


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

    storage = get_storage_adapter()
    quarantine_key = f"quarantine/{session.pk.hex}"

    # If finalization wrote PRIMARY but the database transaction did not commit,
    # that object is an orphan. Remove it best-effort; the staging source remains
    # the canonical input for quarantine.
    if session.final_object_key:
        try:
            storage.delete_object(session.final_object_key)
        except StorageNotFoundError:
            pass
        except StorageError:
            logger.warning(
                "Could not remove orphaned publication object for failed upload %s",
                session.pk,
                exc_info=True,
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
                except StorageError:
                    logger.warning(
                        "Could not abort incomplete multipart upload %s",
                        session.pk,
                        exc_info=True,
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


class Command(BaseCommand):
    help = "Verify and optionally scan staged uploads, publish valid files to PRIMARY, and quarantine permanent failures."

    def handle(self, *args, **options):
        # Recover the DB/storage split if multipart completion succeeded but the
        # web request died before committing its outbox row.
        for upload_id in UploadSession.objects.filter(
            state__in=[UploadSession.State.VERIFYING, UploadSession.State.SCANNING]
        ).values_list("pk", flat=True).iterator():
            UploadFinalizationJob.objects.get_or_create(upload_session_id=upload_id)
        stale_before = timezone.now() - timedelta(minutes=10)
        UploadFinalizationJob.objects.filter(
            state=UploadFinalizationJob.State.PROCESSING, updated_at__lt=stale_before
        ).update(state=UploadFinalizationJob.State.PENDING)
        done = failed = retrying = 0
        for job_id in UploadFinalizationJob.objects.filter(
            state=UploadFinalizationJob.State.PENDING
        ).values_list("pk", flat=True)[:100]:
            with transaction.atomic():
                job = UploadFinalizationJob.objects.select_for_update().select_related(
                    "upload_session__initiated_by"
                ).get(pk=job_id)
                if job.state != UploadFinalizationJob.State.PENDING:
                    continue
                job.state = UploadFinalizationJob.State.PROCESSING
                job.attempts += 1
                job.save(update_fields=["state", "attempts", "updated_at"])
                upload = job.upload_session
            try:
                storage = get_storage_adapter()
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
                if stat.size_bytes != upload.expected_size_bytes or stat.size_bytes > MAX_UPLOAD_SIZE:
                    raise StorageIntegrityError("Completed object size failed verification.")
                source = storage.open_object(upload.object_key)
                try:
                    plaintext = source.read(MAX_UPLOAD_SIZE + 1)
                finally:
                    source.close()
                # actual_size_bytes is populated only after this validation. Compare
                # the downloaded quarantine object with the server-owned expected size.
                if len(plaintext) != upload.expected_size_bytes or len(plaintext) > MAX_UPLOAD_SIZE:
                    raise ValueError("Verified object size changed before finalization.")
                digest = hashlib.sha256(plaintext).hexdigest()
                if upload.expected_sha256 and digest != upload.expected_sha256:
                    raise StorageIntegrityError("Verified object checksum changed before finalization.")
                UploadSession.objects.filter(pk=upload.pk, state=UploadSession.State.VERIFYING).update(
                    received_bytes=len(plaintext), actual_size_bytes=len(plaintext)
                )
                if settings.SECUREDRIVE_UPLOAD_SCANNER:
                    UploadSession.objects.filter(
                        pk=upload.pk, state=UploadSession.State.VERIFYING
                    ).update(state=UploadSession.State.SCANNING)
                finalize_verified_upload(upload, plaintext, upload.initiated_by)
                UploadFinalizationJob.objects.filter(pk=job.pk).update(state=UploadFinalizationJob.State.DONE)
                done += 1
            except Exception as error:
                logger.exception(
                    "Upload finalization failed: upload_id=%s, job_id=%s, "
                    "attempt=%s, error_type=%s, error=%s",
                    upload.pk,
                    job.pk,
                    job.attempts,
                    type(error).__name__,
                    error,
                )
                # A live-name uniqueness race is resolved on a bounded retry;
                # the next transaction observes the winner and picks (2), (3), … .
                transient = isinstance(error, (StorageRetryableError, IntegrityError))
                if transient and job.attempts < 3:
                    UploadFinalizationJob.objects.filter(pk=job.pk).update(state=UploadFinalizationJob.State.PENDING)
                    retrying += 1
                else:
                    UploadSession.objects.filter(pk=upload.pk, state__in=[UploadSession.State.VERIFYING, UploadSession.State.SCANNING]).update(state=UploadSession.State.FAILED, failure_code="finalization_failed")
                    try:
                        finalize_upload_quota(upload.pk, completed=False)
                    except Exception:
                        pass
                    try:
                        quarantined = _quarantine_failed_upload(upload.pk)
                        if not quarantined:
                            logger.warning(
                                "Failed upload was marked failed but its object could not be quarantined: upload_id=%s",
                                upload.pk,
                            )
                    except Exception:
                        # Do not hide the original finalization error. Keep the source
                        # object and metadata so cleanup/reconciliation can retry safely.
                        logger.exception(
                            "Could not quarantine failed upload object: upload_id=%s",
                            upload.pk,
                        )
                    UploadFinalizationJob.objects.filter(pk=job.pk).update(state=UploadFinalizationJob.State.FAILED)
                    failed += 1
        self.stdout.write(f"Finalized: {done}; retrying: {retrying}; failed: {failed}")
