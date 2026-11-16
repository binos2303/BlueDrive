"""Normalize the Free baseline for future allocations; retain existing quotas."""
from django.db import migrations


FREE_MIB = 10 * 1024 * 1024
WORKSPACE_STARTER_MIB = 100 * 1024 * 1024


def ensure_default_storage_plans(apps, schema_editor):
    Plan = apps.get_model("accounts", "StoragePlan")
    plans = Plan.objects.using(schema_editor.connection.alias)
    # The user explicitly selected Free = 10 MiB. This updates the plan
    # definition, not any QuotaAccount allocation or previously stored files.
    plans.update_or_create(
        code="free",
        defaults={
            "name": "Free",
            "scope": "personal",
            "limit_bytes": FREE_MIB,
            "is_active": True,
        },
    )
    # Preserve any admin-customized Workspace Starter size; supply a baseline
    # only when one is absent. Workspace creation uses the live plan size.
    starter, _ = plans.get_or_create(
        code="workspace-starter",
        defaults={
            "name": "Workspace Starter",
            "scope": "workspace",
            "limit_bytes": WORKSPACE_STARTER_MIB,
            "is_active": True,
        },
    )
    if not starter.is_active or starter.scope != "workspace":
        starter.is_active = True
        starter.scope = "workspace"
        starter.save(update_fields=["is_active", "scope", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0009_admin_plans_share_policy")]

    operations = [
        migrations.RunPython(ensure_default_storage_plans, migrations.RunPython.noop),
    ]
