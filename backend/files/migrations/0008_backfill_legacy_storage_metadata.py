from itertools import islice

from django.db import migrations
from django.db.models import Count, F
from django.db.models.functions import Lower


def backfill_legacy_storage_metadata(apps, schema_editor):
    Tenant = apps.get_model("accounts", "Tenant")
    QuotaAccount = apps.get_model("accounts", "QuotaAccount")
    File = apps.get_model("files", "File")
    FileVersion = apps.get_model("files", "FileVersion")
    StorageConfig = apps.get_model("files", "StorageConfig")
    StorageLocation = apps.get_model("files", "StorageLocation")
    database = schema_editor.connection.alias

    tenants_by_owner = dict(
        Tenant.objects.using(database)
        .filter(kind="personal")
        .values_list("personal_owner_id", "pk")
    )
    files = File.objects.using(database)

    missing_owners = list(
        files.exclude(owner_id__in=tenants_by_owner).values_list("pk", flat=True)[:10]
    )
    if missing_owners:
        raise RuntimeError(
            "Cannot backfill file tenants: no personal tenant for file IDs "
            f"{missing_owners}."
        )

    files_in_other_owner_folders = list(
        files.filter(folder__isnull=False)
        .exclude(owner_id=F("folder__owner_id"))
        .values_list("pk", flat=True)[:10]
    )
    if files_in_other_owner_folders:
        raise RuntimeError(
            "Cannot backfill file tenants: file and folder have different owners "
            f"for file IDs {files_in_other_owner_folders}."
        )

    duplicate_names = list(
        files.filter(deleted_at__isnull=True)
        .annotate(normalized_name=Lower("file_name"))
        .values("owner_id", "folder_id", "normalized_name")
        .annotate(item_count=Count("pk"))
        .filter(item_count__gt=1)[:10]
    )
    if duplicate_names:
        raise RuntimeError(
            "Cannot enforce tenant-scoped case-insensitive file names until "
            "legacy live sibling duplicates are resolved."
        )

    negative_sizes = list(
        files.filter(file_size__lt=0).values_list("pk", flat=True)[:10]
    )
    if negative_sizes:
        raise RuntimeError(
            "Cannot create positive file-version sizes for file IDs "
            f"{negative_sizes}; correct the legacy metadata first."
        )

    path_collisions = list(
        files.exclude(file_path="")
        .values("owner_id", "file_path")
        .annotate(item_count=Count("pk"))
        .filter(item_count__gt=1)[:10]
    )
    if path_collisions:
        raise RuntimeError(
            "Cannot create unique storage locations: legacy file paths are reused "
            "within a user account. Resolve the duplicate references first."
        )

    storage_configs = {}
    usage_by_tenant = {}
    file_iterator = files.only(
        "pk",
        "owner_id",
        "tenant_id",
        "file_name",
        "file_path",
        "file_size",
        "mime_type",
        "hash_sha256",
        "is_encrypted",
        "encryption_version",
        "encryption_nonce",
        "wrapped_dek",
        "dek_nonce",
    ).iterator(chunk_size=200)

    while batch := list(islice(file_iterator, 200)):
        versions = []
        locations = []
        for drive_file in batch:
            tenant_id = tenants_by_owner[drive_file.owner_id]
            drive_file.tenant_id = tenant_id
            usage_by_tenant[tenant_id] = (
                usage_by_tenant.get(tenant_id, 0) + drive_file.file_size
            )

            storage_config_id = storage_configs.get(tenant_id)
            if storage_config_id is None:
                storage_config_id = StorageConfig.objects.using(database).create(
                    tenant_id=tenant_id,
                    provider="local",
                    status="active",
                ).pk
                storage_configs[tenant_id] = storage_config_id

            has_storage_path = bool(drive_file.file_path)
            version = FileVersion(
                tenant_id=tenant_id,
                file_id=drive_file.pk,
                version_number=1,
                state="pending" if has_storage_path else "failed",
                size_bytes=drive_file.file_size,
                mime_type=drive_file.mime_type,
                sha256=drive_file.hash_sha256,
                is_current=True,
                is_encrypted=drive_file.is_encrypted,
                encryption_version=drive_file.encryption_version,
                encryption_nonce=drive_file.encryption_nonce,
                wrapped_dek=drive_file.wrapped_dek,
                dek_nonce=drive_file.dek_nonce,
            )
            versions.append(version)
            if has_storage_path:
                locations.append(
                    StorageLocation(
                        tenant_id=tenant_id,
                        file_version_id=version.pk,
                        storage_config_id=storage_config_id,
                        object_ref=drive_file.file_path,
                        state="pending",
                        size_bytes=drive_file.file_size,
                        checksum=drive_file.hash_sha256,
                    )
                )

        files.bulk_update(batch, ["tenant"], batch_size=200)
        FileVersion.objects.using(database).bulk_create(
            versions,
            batch_size=100,
        )
        StorageLocation.objects.using(database).bulk_create(
            locations,
            batch_size=100,
        )

    for tenant_id, used_bytes in usage_by_tenant.items():
        QuotaAccount.objects.using(database).filter(
            tenant_id=tenant_id,
            scope="tenant",
        ).update(used_bytes=used_bytes)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_create_personal_tenants"),
        ("files", "0007_fileversion_quotareservation_storageconfig_and_more"),
        ("folders", "0008_backfill_personal_tenant"),
    ]

    operations = [
        migrations.RunPython(backfill_legacy_storage_metadata),
    ]
