from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_workspace_events(apps, schema_editor):
    ActivityLog = apps.get_model("logs", "ActivityLog")
    Workspace = apps.get_model("accounts", "Workspace")
    File = apps.get_model("files", "File")
    Folder = apps.get_model("folders", "Folder")
    ContentType = apps.get_model("contenttypes", "ContentType")

    file_type = ContentType.objects.filter(app_label="files", model="file").first()
    folder_type = ContentType.objects.filter(app_label="folders", model="folder").first()

    for row in ActivityLog.objects.filter(workspace__isnull=True).only(
        "id", "content_type_id", "object_id", "metadata"
    ).iterator(chunk_size=500):
        workspace_id = None
        metadata = row.metadata if isinstance(row.metadata, dict) else {}
        supplied_id = metadata.get("workspace_id")
        if supplied_id:
            workspace_id = Workspace.objects.filter(pk=supplied_id).values_list("pk", flat=True).first()
        if workspace_id is None and row.object_id:
            if file_type and row.content_type_id == file_type.pk:
                workspace_id = File.objects.filter(pk=row.object_id).values_list("workspace_id", flat=True).first()
            elif folder_type and row.content_type_id == folder_type.pk:
                workspace_id = Folder.objects.filter(pk=row.object_id).values_list("workspace_id", flat=True).first()
        if workspace_id is not None:
            ActivityLog.objects.filter(pk=row.pk).update(workspace_id=workspace_id)


def noop(apps, schema_editor):
    return


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_workspace_invites_and_default_role"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("files", "0014_workspace"),
        ("folders", "0010_workspace"),
        ("logs", "0010_workspace_group_audit_actions"),
    ]

    operations = [
        migrations.AddField(
            model_name="activitylog",
            name="workspace",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="activity_logs", to="accounts.workspace"),
        ),
        migrations.AlterField(
            model_name="activitylog",
            name="action",
            field=models.CharField(
                choices=[
                    ("LOGIN", "Login"),
                    ("LOGOUT", "Logout"),
                    ("UPLOAD", "Upload"),
                    ("DOWNLOAD", "Download"),
                    ("VIEW", "View"),
                    ("COPY", "Copy"),
                    ("CUT", "Cut"),
                    ("MOVE", "Move"),
                    ("RENAME", "Rename"),
                    ("DELETE", "Move to Trash"),
                    ("RESTORE", "Restore"),
                    ("PERMANENT_DELETE", "Permanent delete"),
                    ("CREATE_FOLDER", "Create folder"),
                    ("ENCRYPT", "Encrypt"),
                    ("DECRYPT", "Decrypt"),
                    ("SHARE", "Share"),
                    ("REVOKE_SHARE", "Revoke share"),
                    ("SUSPEND_MEMBER", "Suspend tenant member"),
                    ("RESTORE_MEMBER", "Restore tenant member"),
                    ("CREATE_WORKSPACE", "Create workspace"),
                    ("UPDATE_WORKSPACE", "Update workspace"),
                    ("CREATE_GROUP", "Create group"),
                    ("UPDATE_GROUP", "Update group"),
                    ("ADD_GROUP_MEMBER", "Add group member"),
                    ("REMOVE_GROUP_MEMBER", "Remove group member"),
                    ("ADD_WORKSPACE_MEMBER", "Add workspace member"),
                    ("REMOVE_WORKSPACE_MEMBER", "Remove workspace member"),
                    ("GRANT_WORKSPACE_GROUP", "Grant group workspace access"),
                    ("REVOKE_WORKSPACE_GROUP", "Revoke group workspace access"),
                    ("INVITE_WORKSPACE_MEMBER", "Invite workspace member"),
                    ("JOIN_WORKSPACE", "Join workspace"),
                ],
                max_length=30,
            ),
        ),
        migrations.AddIndex(
            model_name="activitylog",
            index=models.Index(fields=["workspace", "-created_at"], name="activity_workspace_time_idx"),
        ),
        migrations.RunPython(backfill_workspace_events, noop),
    ]
