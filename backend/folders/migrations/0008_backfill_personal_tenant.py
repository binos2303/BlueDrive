from itertools import islice

from django.db import migrations
from django.db.models import Count, F
from django.db.models.functions import Lower


def backfill_personal_tenant(apps, schema_editor):
    Tenant = apps.get_model("accounts", "Tenant")
    Folder = apps.get_model("folders", "Folder")
    database = schema_editor.connection.alias

    tenants_by_owner = dict(
        Tenant.objects.using(database)
        .filter(kind="personal")
        .values_list("personal_owner_id", "pk")
    )
    folders = Folder.objects.using(database)

    missing_owners = list(
        folders.exclude(owner_id__in=tenants_by_owner).values_list("pk", flat=True)[:10]
    )
    if missing_owners:
        raise RuntimeError(
            "Cannot backfill folder tenants: no personal tenant for folder IDs "
            f"{missing_owners}."
        )

    cross_owner_parent = list(
        folders.filter(parent__isnull=False)
        .exclude(owner_id=F("parent__owner_id"))
        .values_list("pk", flat=True)[:10]
    )
    if cross_owner_parent:
        raise RuntimeError(
            "Cannot backfill folder tenants: parent and child have different owners "
            f"for folder IDs {cross_owner_parent}."
        )

    duplicate_names = list(
        folders.filter(deleted_at__isnull=True)
        .annotate(normalized_name=Lower("folder_name"))
        .values("owner_id", "parent_id", "normalized_name")
        .annotate(item_count=Count("pk"))
        .filter(item_count__gt=1)[:10]
    )
    if duplicate_names:
        raise RuntimeError(
            "Cannot enforce tenant-scoped case-insensitive folder names until "
            "legacy live sibling duplicates are resolved."
        )

    folder_iterator = folders.only("pk", "owner_id").iterator(chunk_size=500)
    while batch := list(islice(folder_iterator, 500)):
        for folder in batch:
            folder.tenant_id = tenants_by_owner[folder.owner_id]
        folders.bulk_update(batch, ["tenant"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_create_personal_tenants"),
        ("folders", "0007_folder_purge_after_folder_tenant_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_personal_tenant),
    ]
