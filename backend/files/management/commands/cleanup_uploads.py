from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from files.models import QuotaReservation, StorageLocation, UploadSession
from files.quota import QuotaStateError, finalize_upload_quota
from files.storage_adapters import get_storage_adapter
from files.storage_adapters.base import StorageError, StorageIntegrityError
from files.storage_routing import adapter_for_upload


class Command(BaseCommand):
    help = "Abort expired multipart uploads and release their quota reservations."

    def handle(self, *args, **options):
        now = timezone.now()
        published = ('available','completed')
        pending_keys = ~Q(object_key='') | ~Q(provider_upload_id='') | ~Q(final_object_key='') | Q(quota_reservations__state='reserved')
        eligible = (Q(expires_at__lte=now,state__in=['initiated','uploading','expired','failed']) | Q(state='canceled')) & pending_keys
        eligible |= Q(expires_at__lte=now,state__in=published) & (~Q(object_key='') | ~Q(provider_upload_id=''))
        ids = UploadSession.objects.filter(eligible).order_by('expires_at','pk').values_list('pk',flat=True).distinct()[:100]
        cleaned = pending = 0
        for upload_id in list(ids):
            with transaction.atomic():
                session = UploadSession.objects.select_related('tenant','storage_config','storage_connection__cluster').select_for_update(of=('self',)).get(pk=upload_id)
                if session.state in ('verifying','scanning') or (session.state != 'canceled' and session.expires_at > now):
                    continue
                if session.state not in (*published,'initiated','uploading','expired','failed','canceled'):
                    continue
                if session.state in ('initiated','uploading'):
                    session.state = 'expired'
                    session.failure_code = 'expired'
                    session.save(update_fields=['state','failure_code','updated_at'])
                if session.state not in published and QuotaReservation.objects.filter(upload_session=session,state='reserved').exists():
                    try:
                        finalize_upload_quota(session.pk,completed=False)
                    except QuotaStateError:
                        pending += 1
                        continue
                claimed_state = session.state
            try:
                keys = {session.object_key} - {''}
                if claimed_state not in published:
                    keys.update({session.final_object_key} - {''})
                if claimed_state == UploadSession.State.FAILED and session.object_key:
                    # Copy quarantine có thể đã commit ở S3 trong khi DB chưa đổi key.
                    keys.add(f"quarantine/{session.pk.hex}")
                if StorageLocation.objects.filter(object_ref__in=keys).exists():
                    # Không dựa vào tenant/state để suy đoán key là độc quyền vật lý.
                    raise StorageIntegrityError("An upload cleanup key is still referenced.")
                adapter = adapter_for_upload(session,fallback=get_storage_adapter,cleanup=True)
                if session.provider_upload_id:
                    adapter.abort_multipart(session.object_key, session.provider_upload_id)
                for key in sorted(keys):
                    adapter.delete_object(key)
                with transaction.atomic():
                    current = UploadSession.objects.select_for_update().get(pk=session.pk)
                    if current.state == claimed_state:
                        current.object_key = current.provider_upload_id = ''
                        fields = ['object_key','provider_upload_id','updated_at']
                        if current.state not in published:
                            current.final_object_key = ''
                            fields.append('final_object_key')
                        current.save(update_fields=fields)
                cleaned += 1
            except StorageError:
                pending += 1
        self.stdout.write(f"Expired sessions cleaned: {cleaned}; cleanup pending: {pending}")
