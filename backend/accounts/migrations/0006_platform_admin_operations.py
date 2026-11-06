# BlueDrive Phase 02: user administration audit and observed database sessions.
import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_workspace_invites_and_default_role"),
        ("sessions", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TrackedAccountSession",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now_add=True)),
                ("user_agent", models.CharField(max_length=255, blank=True)),
                ("session", models.OneToOneField(to="sessions.session", on_delete=django.db.models.deletion.CASCADE, related_name="account_tracking")),
                ("user", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE, related_name="tracked_sessions")),
            ],
            options={"indexes": [models.Index(fields=["user", "-last_seen_at"], name="acct_session_usr_seen_idx")]},
        ),
        migrations.CreateModel(
            name="PlatformAdminAuditEvent",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("action", models.CharField(max_length=32, choices=[("user.suspend", "Suspend account"), ("user.reactivate", "Reactivate account"), ("session.revoke", "Revoke session")])),
                ("reason", models.CharField(max_length=500)),
                ("metadata", models.JSONField(default=dict, blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT, related_name="platform_audit_actions")),
                ("target_user", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT, related_name="platform_audit_targets")),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["-created_at"], name="platform_audit_created_idx"),
                    models.Index(fields=["target_user", "-created_at"], name="platform_audit_target_idx"),
                ],
            },
        ),
    ]
