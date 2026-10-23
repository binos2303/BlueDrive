import django.db.models.deletion
from django.db import migrations, models
from django.db.models.functions import Lower


def backfill_folder_workspace(apps, schema_editor):
    database = schema_editor.connection.alias
    Folder = apps.get_model("folders", "Folder")
    Workspace = apps.get_model("accounts", "Workspace")
    for workspace in Workspace.objects.using(database).filter(is_default=True).iterator(chunk_size=500):
        Folder.objects.using(database).filter(
            tenant_id=workspace.tenant_id,
            workspace__isnull=True,
        ).update(workspace_id=workspace.pk)


def workspace_constraints(apps, schema_editor, *, add):
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.quote_name
    folder = quote(apps.get_model("folders", "Folder")._meta.db_table)
    workspace = quote(apps.get_model("accounts", "Workspace")._meta.db_table)
    statements = [
        (
            "folder_workspace_tenant_fk",
            f"FOREIGN KEY ({quote('tenant_id')}, {quote('workspace_id')}) "
            f"REFERENCES {workspace} ({quote('tenant_id')}, {quote('id')}) "
            "ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED",
        ),
        (
            "folder_parent_same_workspace_fk",
            f"FOREIGN KEY ({quote('workspace_id')}, {quote('parent_id')}) "
            f"REFERENCES {folder} ({quote('workspace_id')}, {quote('id')}) "
            "ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED",
        ),
    ]
    for name, definition in statements:
        if add:
            schema_editor.execute(f"ALTER TABLE {folder} ADD CONSTRAINT {quote(name)} {definition}")
        else:
            schema_editor.execute(f"ALTER TABLE {folder} DROP CONSTRAINT {quote(name)}")


def add_workspace_constraints(apps, schema_editor):
    workspace_constraints(apps, schema_editor, add=True)


def remove_workspace_constraints(apps, schema_editor):
    workspace_constraints(apps, schema_editor, add=False)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_workspace_groups"),
        ("folders", "0009_alter_folder_tenant"),
    ]

    operations = [
        migrations.AddField(
            model_name="folder",
            name="workspace",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="folders", to="accounts.workspace"),
        ),
        migrations.RunPython(backfill_folder_workspace, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="folder",
            name="workspace",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="folders", to="accounts.workspace"),
        ),
        migrations.RemoveConstraint(model_name="folder", name="folder_live_root_name_uniq"),
        migrations.RemoveConstraint(model_name="folder", name="folder_live_child_name_uniq"),
        migrations.AddConstraint(
            model_name="folder",
            constraint=models.UniqueConstraint(models.F("workspace"), Lower("folder_name"), condition=models.Q(("parent__isnull", True), ("deleted_at__isnull", True)), name="folder_live_root_name_uniq"),
        ),
        migrations.AddConstraint(
            model_name="folder",
            constraint=models.UniqueConstraint(models.F("workspace"), models.F("parent"), Lower("folder_name"), condition=models.Q(("parent__isnull", False), ("deleted_at__isnull", True)), name="folder_live_child_name_uniq"),
        ),
        migrations.AddConstraint(
            model_name="folder",
            constraint=models.UniqueConstraint(fields=("workspace", "id"), name="folder_workspace_id_uniq"),
        ),
        migrations.AddIndex(
            model_name="folder",
            index=models.Index(fields=["workspace", "parent", "deleted_at"], name="folder_ws_parent_del_idx"),
        ),
        migrations.AddIndex(
            model_name="folder",
            index=models.Index(fields=["workspace", "owner", "deleted_at"], name="folder_ws_owner_del_idx"),
        ),
        migrations.RunPython(add_workspace_constraints, remove_workspace_constraints),
    ]
