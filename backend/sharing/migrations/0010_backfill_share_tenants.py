from itertools import islice

from django.db import migrations


def backfill_share_tenants(apps, schema_editor):
    Share = apps.get_model("sharing", "Share")
    File = apps.get_model("files", "File")
    Folder = apps.get_model("folders", "Folder")
    database = schema_editor.connection.alias

    share_iterator = Share.objects.using(database).only(
        "pk", "file_id", "folder_id"
    ).iterator(chunk_size=500)
    while batch := list(islice(share_iterator, 500)):
        file_ids = {share.file_id for share in batch if share.file_id is not None}
        folder_ids = {
            share.folder_id for share in batch if share.folder_id is not None
        }
        tenants_by_file = dict(
            File.objects.using(database)
            .filter(pk__in=file_ids)
            .values_list("pk", "tenant_id")
        )
        tenants_by_folder = dict(
            Folder.objects.using(database)
            .filter(pk__in=folder_ids)
            .values_list("pk", "tenant_id")
        )
        unresolved = []
        for share in batch:
            tenant_id = (
                tenants_by_file.get(share.file_id)
                if share.file_id is not None
                else tenants_by_folder.get(share.folder_id)
            )
            if tenant_id is None:
                unresolved.append(share.pk)
            else:
                share.tenant_id = tenant_id
        if unresolved:
            raise RuntimeError(
                "Cannot backfill share tenants: target resource is missing or has "
                f"no tenant for share IDs {unresolved[:10]}."
            )
        Share.objects.using(database).bulk_update(
            batch,
            ["tenant"],
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("files", "0008_backfill_legacy_storage_metadata"),
        ("folders", "0008_backfill_personal_tenant"),
        ("sharing", "0009_share_tenant_share_share_tenant_owner_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_share_tenants),
    ]
