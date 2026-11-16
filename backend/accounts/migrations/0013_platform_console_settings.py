from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_admin_file_operations")]

    operations = [
        migrations.CreateModel(
            name="PlatformConsoleSettings",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("display_name", models.CharField(default="BlueDrive", max_length=80)),
                ("revision", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="platformconsolesettings",
            constraint=models.CheckConstraint(condition=models.Q(id=1), name="platform_console_singleton_id"),
        ),
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
                ("settings.update", "Update console settings"),
            ]),
        ),
    ]
