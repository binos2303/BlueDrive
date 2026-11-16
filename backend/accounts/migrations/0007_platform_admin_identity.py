import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_platform_admin_operations"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformAdminIdentity",
            fields=[
                ("user", models.OneToOneField(primary_key=True, serialize=False, on_delete=django.db.models.deletion.PROTECT,
                                              related_name="platform_admin_identity", to=settings.AUTH_USER_MODEL)),
                ("status", models.CharField(max_length=12, default="invited", choices=[
                    ("invited", "Invited"), ("active", "Active"), ("disabled", "Disabled")
                ])),
                ("invited_at", models.DateTimeField(auto_now_add=True)),
                ("activated_at", models.DateTimeField(null=True, blank=True)),
                ("invited_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT,
                                                 related_name="platform_admin_invitations_created")),
            ],
            options={"verbose_name": "Dedicated Platform Administrator", "verbose_name_plural": "Dedicated Platform Administrators"},
        ),
        migrations.AlterField(
            model_name="platformadminauditevent", name="action", field=models.CharField(max_length=32, choices=[
                ("user.suspend", "Suspend account"), ("user.reactivate", "Reactivate account"),
                ("session.revoke", "Revoke session"), ("admin.invite", "Invite administrator"),
                ("admin.accept", "Accept administrator invitation"), ("admin.disable", "Disable administrator"),
            ]),
        ),
    ]
