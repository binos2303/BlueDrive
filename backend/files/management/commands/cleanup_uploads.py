from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from files.models import UploadSession
from files.quota import QuotaStateError, finalize_upload_quota
from files.storage_adapters import get_storage_adapter
from files.storage_adapters.base import StorageError


class Command(BaseCommand):
    help = "Abort expired multipart uploads and release their quota reservations."

    def handle(self, *args, **options):
        now = timezone.now()
        sessions = UploadSession.objects.filter(
            (Q(expires_at__lte=now, state__in=[UploadSession.State.INITIATED, UploadSession.State.UPLOADING, UploadSession.State.EXPIRED, UploadSession.State.AVAILABLE])
             | Q(state=UploadSession.State.CANCELED)
             | Q(expires_at__lte=now, state=UploadSession.State.FAILED))
        ).order_by("expires_at")
        adapter = get_storage_adapter()
        cleaned = pending = 0
        for session in sessions.iterator():
            try:
                if session.provider_upload_id:
                    adapter.abort_multipart(session.object_key, session.provider_upload_id)
                if session.object_key:
                    adapter.delete_object(session.object_key)
                if session.final_object_key and session.state != UploadSession.State.AVAILABLE:
                    adapter.delete_object(session.final_object_key)
                with transaction.atomic():
                    locked = UploadSession.objects.select_for_update().get(pk=session.pk)
                    if locked.state not in (UploadSession.State.COMPLETED, UploadSession.State.AVAILABLE, UploadSession.State.CANCELED):
                        locked.state = UploadSession.State.EXPIRED
                        locked.failure_code = "expired"
                        locked.save(update_fields=["state", "failure_code", "updated_at"])
                        try:
                            finalize_upload_quota(locked.pk, completed=False)
                        except QuotaStateError:
                            pass
                cleaned += 1
            except StorageError:
                pending += 1
        self.stdout.write(f"Expired sessions cleaned: {cleaned}; cleanup pending: {pending}")
