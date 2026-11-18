import json
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from files.models import File, QuotaReservation, StorageLocation, UploadSession
from files.storage_adapters import get_storage_adapter
from files.storage_adapters.base import StorageError, StorageNonRetryableError, StorageNotFoundError
from files.storage_routing import adapter_for_location, adapter_for_upload


class Command(BaseCommand):
    help = "Report recovery evidence for one upload. Does not change database or storage."

    def add_arguments(self, parser):
        parser.add_argument("upload_id", type=UUID)
        parser.add_argument("--inspect-storage", action="store_true",
                            help="Read exact keys and pinned versions from the session's original storage.")

    def handle(self, *args, **options):
        upload = UploadSession.objects.select_related("tenant", "storage_config", "storage_connection__cluster").filter(
            pk=options["upload_id"],
        ).first()
        if upload is None:
            raise CommandError("Upload session was not found.")
        locations = list(StorageLocation.objects.filter(file_version__file_id=upload.file_id).select_related(
            "storage_config", "storage_connection__cluster", "tenant",
        )) if upload.file_id else []
        terminal_states = {
            UploadSession.State.AVAILABLE, UploadSession.State.COMPLETED,
            UploadSession.State.FAILED, UploadSession.State.CANCELED, UploadSession.State.EXPIRED,
        }
        terminal = upload.state in terminal_states
        expired = upload.expires_at <= timezone.now()
        quarantine_key = f"quarantine/{upload.pk.hex}"
        result = {
            "mode": "report_only",
            "state": upload.state,
            "terminal_reserved_quota": upload.quota_reservations.filter(
                state=QuotaReservation.State.RESERVED,
            ).count() if terminal else 0,
            "expired_multipart_recorded": bool(expired and upload.provider_upload_id),
            "file_purge_started": bool(upload.file_id and File.objects.filter(
                pk=upload.file_id, purge_started_at__isnull=False,
            ).exists()),
            "pending_deletion_locations": sum(row.state in {"delete_pending", "error"} for row in locations),
            "quarantine_recorded": upload.object_key == quarantine_key,
            "storage": "not_checked",
        }
        if options["inspect_storage"]:
            try:
                result.update(self.inspect_storage(upload, locations, terminal, expired, quarantine_key))
            except StorageError as error:
                result.update(storage="unknown", error_type=type(error).__name__)
        self.stdout.write(json.dumps(result, sort_keys=True))

    def inspect_storage(self, upload, locations, terminal, expired, quarantine_key):
        missing = 0
        for location in locations:
            if location.state != StorageLocation.State.AVAILABLE:
                continue
            storage = adapter_for_location(location, fallback=get_storage_adapter, cleanup=True)
            try:
                storage.stat_object(location.object_ref, version_id=location.provider_version_id)
            except StorageNotFoundError:
                missing += 1

        storage = adapter_for_upload(upload, fallback=get_storage_adapter, cleanup=True)
        expired_multipart = False
        if expired and upload.object_key and upload.provider_upload_id:
            try:
                storage.list_uploaded_parts(upload.object_key, upload.provider_upload_id)
            except (StorageNotFoundError, StorageNonRetryableError) as error:
                if not isinstance(error, StorageNotFoundError) and getattr(error, "provider_code", "") != "NoSuchUpload":
                    raise
            else:
                expired_multipart = True
        keys = {upload.object_key, upload.final_object_key} - {""}
        if upload.state == UploadSession.State.FAILED:
            keys.add(quarantine_key)
        unreferenced = quarantine_versions = 0
        for key in sorted(keys):
            versions = storage.list_exact_versions(key)
            refs = list(StorageLocation.objects.filter(object_ref=key).values_list("provider_version_id", flat=True))
            if key == quarantine_key:
                quarantine_versions = len(versions)
            if terminal and "" not in refs:
                # Chỉ là ứng viên cần đối chiếu. Claim cũ có thể còn RPC đang chạy.
                unreferenced += sum(version["VersionId"] not in refs for version in versions)
        return {
            "storage": "observed",
            "missing_available_locations": missing,
            "unreferenced_known_key_versions": unreferenced,
            "quarantine_versions": quarantine_versions,
            "expired_multipart_present": expired_multipart,
        }
