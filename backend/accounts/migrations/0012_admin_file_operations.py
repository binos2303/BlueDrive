# Extend platform-audit action vocabulary; no database table added.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0011_remove_custom_groups")]

    operations = [
        migrations.AlterField(
            model_name="platformadminauditevent", name="action",
            field=models.CharField(max_length=32, choices=[
                ("user.suspend", "Suspend account"),
                ("user.reactivate", "Reactivate account"),
                ("session.revoke", "Revoke session"),
                ("admin.invite", "Invite administrator"),
                ("admin.accept", "Accept administrator invitation"),
                ("admin.disable", "Disable administrator"),
                ("file.trash", "Move file to Trash"),
                ("file.restore", "Restore file"),
                ("file.purge.requested", "Request file purge"),
                ("file.purge.succeeded", "Complete file purge"),
                ("file.purge.failed", "File purge failed"),
            ]),
        ),
    ]
