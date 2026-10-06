from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("logs", "0005_activitylog_resource"),
    ]

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
                ],
                max_length=30,
            ),
        ),
    ]
