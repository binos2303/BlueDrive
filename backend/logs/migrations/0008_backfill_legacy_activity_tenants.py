from django.db import migrations
from django.db.models import OuterRef, Subquery


def backfill_legacy_activity_tenants(apps, schema_editor):
    Tenant = apps.get_model("accounts", "Tenant")
    ActivityLog = apps.get_model("logs", "ActivityLog")
    database = schema_editor.connection.alias

    personal_tenant = Tenant.objects.using(database).filter(
        kind="personal",
        personal_owner_id=OuterRef("user_id"),
    )
    ActivityLog.objects.using(database).filter(
        tenant__isnull=True,
    ).update(
        tenant_id=Subquery(personal_tenant.values("pk")[:1])
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_create_personal_tenants"),
        ("logs", "0007_activitylog_metadata_activitylog_request_id_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_legacy_activity_tenants),
    ]
