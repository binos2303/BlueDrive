from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("logs", "0009_alter_activitylog_action")]

    operations = [
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
                ],
                max_length=30,
            ),
        ),
    ]
