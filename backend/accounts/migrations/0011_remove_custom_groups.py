"""Remove BlueDrive's custom Group permission mechanism (not Django auth.Group).

Prior to applying, verify that Group-related data is absent in this database.
The guard fails loudly on installations that still require permission migration.
"""
from django.db import migrations


def require_empty_groups(apps, schema_editor):
    alias = schema_editor.connection.alias
    for name in ("WorkspaceGroupAccess", "GroupMembership", "Group"):
        model = apps.get_model("accounts", name)
        if model.objects.using(alias).exists():
            raise RuntimeError(
                f"Cannot remove accounts.{name}: rows exist in {alias}. "
                "Export and migrate grants to direct WorkspaceMembership before retrying."
            )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_starting_storage_plans")]

    operations = [
        migrations.RunPython(require_empty_groups, migrations.RunPython.noop),
        migrations.DeleteModel(name="WorkspaceGroupAccess"),
        migrations.DeleteModel(name="GroupMembership"),
        migrations.DeleteModel(name="Group"),
    ]
