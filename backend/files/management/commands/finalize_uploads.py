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
from files.storage_adapters.base import MultipartPart, StorageIntegrityError, StorageRetryableError
from files.validators import MAX_UPLOAD_SIZE
import logging

logger = logging.getLogger(__name__)


PART_SIZE = 8 * 1024 * 1024


class Command(BaseCommand):
    help = "Verify, optionally scan, encrypt and publish completed multipart uploads."

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
                    UploadFinalizationJob.objects.filter(pk=job.pk).update(state=UploadFinalizationJob.State.FAILED)
                    failed += 1
        self.stdout.write(f"Finalized: {done}; retrying: {retrying}; failed: {failed}")
