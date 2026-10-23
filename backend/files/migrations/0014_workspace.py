import django.db.models.deletion
from django.db import migrations, models
from django.db.models.functions import Coalesce, Lower


def backfill_file_and_upload_workspace(apps, schema_editor):
    database = schema_editor.connection.alias
    Workspace = apps.get_model("accounts", "Workspace")
    Folder = apps.get_model("folders", "Folder")
    File = apps.get_model("files", "File")
    UploadSession = apps.get_model("files", "UploadSession")

    for workspace in Workspace.objects.using(database).filter(is_default=True).iterator(chunk_size=500):
        File.objects.using(database).filter(
            tenant_id=workspace.tenant_id,
            workspace__isnull=True,
        ).update(workspace_id=workspace.pk)
        UploadSession.objects.using(database).filter(
            tenant_id=workspace.tenant_id,
            target_folder__isnull=True,
            workspace__isnull=True,
        ).update(workspace_id=workspace.pk)

    UploadSession.objects.using(database).filter(
        workspace__isnull=True,
        target_folder__isnull=False,
    ).update(workspace_id=models.Subquery(
        Folder.objects.using(database).filter(pk=models.OuterRef("target_folder_id")).values("workspace_id")[:1]
    ))


def workspace_constraints(apps, schema_editor, *, add):
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.quote_name
    file_table = quote(apps.get_model("files", "File")._meta.db_table)
    upload_table = quote(apps.get_model("files", "UploadSession")._meta.db_table)
    folder_table = quote(apps.get_model("folders", "Folder")._meta.db_table)
    workspace_table = quote(apps.get_model("accounts", "Workspace")._meta.db_table)
    statements = [
        (
            file_table,
            "file_workspace_tenant_fk",
            f"FOREIGN KEY ({quote('tenant_id')}, {quote('workspace_id')}) "
            f"REFERENCES {workspace_table} ({quote('tenant_id')}, {quote('id')}) "
            "ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED",
        ),
        (
            file_table,
            "file_folder_same_workspace_fk",
            f"FOREIGN KEY ({quote('workspace_id')}, {quote('folder_id')}) "
            f"REFERENCES {folder_table} ({quote('workspace_id')}, {quote('id')}) "
            "ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED",
        ),
        (
            upload_table,
            "upload_workspace_tenant_fk",
            f"FOREIGN KEY ({quote('tenant_id')}, {quote('workspace_id')}) "
            f"REFERENCES {workspace_table} ({quote('tenant_id')}, {quote('id')}) "
            "ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED",
        ),
        (
            upload_table,
            "upload_folder_same_workspace_fk",
            f"FOREIGN KEY ({quote('workspace_id')}, {quote('target_folder_id')}) "
            f"REFERENCES {folder_table} ({quote('workspace_id')}, {quote('id')}) "
            "ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED",
        ),
        (
            upload_table,
            "upload_file_same_workspace_fk",
            f"FOREIGN KEY ({quote('workspace_id')}, {quote('file_id')}) "
            f"REFERENCES {file_table} ({quote('workspace_id')}, {quote('id')}) "
            "ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED",
        ),
    ]
    for table, name, definition in statements:
        if add:
            schema_editor.execute(f"ALTER TABLE {table} ADD CONSTRAINT {quote(name)} {definition}")
        else:
            schema_editor.execute(f"ALTER TABLE {table} DROP CONSTRAINT {quote(name)}")


def add_workspace_constraints(apps, schema_editor):
    workspace_constraints(apps, schema_editor, add=True)


def remove_workspace_constraints(apps, schema_editor):
    workspace_constraints(apps, schema_editor, add=False)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_workspace_groups"),
        ("files", "0013_fileversion_quarantined_state"),
        ("folders", "0010_workspace"),
    ]

    operations = [
        migrations.AddField(
            model_name="file",
            name="workspace",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="files", to="accounts.workspace"),
        ),
        migrations.AddField(
            model_name="uploadsession",
            name="workspace",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="upload_sessions", to="accounts.workspace"),
        ),
        migrations.RunPython(backfill_file_and_upload_workspace, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="file",
            name="workspace",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="files", to="accounts.workspace"),
        ),
        migrations.AlterField(
            model_name="uploadsession",
            name="workspace",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="upload_sessions", to="accounts.workspace"),
        ),
        migrations.RemoveConstraint(model_name="file", name="file_live_sibling_name_uniq"),
        migrations.AddConstraint(
            model_name="file",
            constraint=models.UniqueConstraint(models.F("workspace"), Coalesce("folder", models.Value(-1, output_field=models.BigIntegerField())), Lower("file_name"), condition=models.Q(("deleted_at__isnull", True)), name="file_live_sibling_name_uniq"),
        ),
        migrations.AddConstraint(
            model_name="file",
            constraint=models.UniqueConstraint(fields=("workspace", "id"), name="file_workspace_id_uniq"),
        ),
        migrations.AddConstraint(
            model_name="uploadsession",
            constraint=models.UniqueConstraint(fields=("workspace", "id"), name="upload_workspace_id_uniq"),
        ),
        migrations.AddIndex(
            model_name="file",
            index=models.Index(fields=["workspace", "folder", "deleted_at"], name="file_ws_folder_del_idx"),
        ),
        migrations.AddIndex(
            model_name="file",
            index=models.Index(fields=["workspace", "owner", "deleted_at"], name="file_ws_owner_del_idx"),
        ),
        migrations.AddIndex(
            model_name="uploadsession",
            index=models.Index(fields=["workspace", "state", "expires_at"], name="upload_ws_state_exp_idx"),
        ),
        migrations.RunPython(add_workspace_constraints, remove_workspace_constraints),
    ]
