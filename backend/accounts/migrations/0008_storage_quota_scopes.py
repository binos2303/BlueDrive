import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


def seed_plans(apps, schema_editor):
    Plan = apps.get_model("accounts", "StoragePlan")
    mib = 1024 ** 2
    plans = [
        ("development", "Development", "personal", 100 * mib),
        ("free", "Free", "personal", 2 * 1024 * mib),
        ("personal", "Personal", "personal", 50 * 1024 * mib),
        ("pro", "Pro", "personal", 200 * 1024 * mib),
        ("premium", "Premium", "personal", 1024 * 1024 * mib),
        ("workspace-starter", "Workspace Starter", "workspace", 100 * mib),
        ("workspace-team", "Workspace Team", "workspace", 20 * 1024 * mib),
        ("workspace-business", "Workspace Business", "workspace", 100 * 1024 * mib),
    ]
    for code, name, scope, limit in plans:
        Plan.objects.get_or_create(code=code, defaults={"name": name, "scope": scope, "limit_bytes": limit})


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_platform_admin_identity"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(name="StoragePlan", fields=[
            ("code", models.SlugField(max_length=48, primary_key=True, serialize=False)),
            ("name", models.CharField(max_length=80)),
            ("scope", models.CharField(max_length=16, choices=[("personal", "Personal Drive"), ("workspace", "Workspace")])),
            ("limit_bytes", models.BigIntegerField()),
            ("is_active", models.BooleanField(default=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"ordering": ["scope", "limit_bytes", "code"]}),
        migrations.AddConstraint(model_name="storageplan", constraint=models.CheckConstraint(condition=Q(limit_bytes__gte=0), name="storage_plan_limit_nonneg")),
        migrations.AddField(model_name="quotaaccount", name="workspace", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="quota_accounts", to="accounts.workspace")),
        migrations.AddField(model_name="quotaaccount", name="plan", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assignments", to="accounts.storageplan")),
        migrations.AlterField(model_name="quotaaccount", name="scope", field=models.CharField(choices=[("tenant", "Tenant"), ("member", "Member"), ("workspace", "Workspace")], max_length=16)),
        migrations.RemoveConstraint(model_name="quotaaccount", name="quota_scope_user_check"),
        migrations.AddConstraint(model_name="quotaaccount", constraint=models.CheckConstraint(condition=(Q(scope="tenant", user__isnull=True, workspace__isnull=True) | Q(scope="member", user__isnull=False, workspace__isnull=True) | Q(scope="workspace", user__isnull=True, workspace__isnull=False)), name="quota_scope_user_check")),
        migrations.AddConstraint(model_name="quotaaccount", constraint=models.UniqueConstraint(fields=["workspace"], condition=Q(scope="workspace"), name="quota_workspace_uniq")),
        migrations.CreateModel(name="QuotaAuditEvent", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("old_limit_bytes", models.BigIntegerField(null=True)),
            ("new_limit_bytes", models.BigIntegerField(null=True)),
            ("old_plan_code", models.CharField(blank=True, max_length=48)),
            ("new_plan_code", models.CharField(blank=True, max_length=48)),
            ("reason", models.CharField(max_length=500)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("quota_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="audit_events", to="accounts.quotaaccount")),
        ], options={"ordering": ["-created_at", "-id"]}),
        migrations.AddIndex(model_name="quotaauditevent", index=models.Index(fields=["quota_account", "created_at"], name="quota_audit_account_dt_idx")),
        migrations.RunPython(seed_plans, migrations.RunPython.noop),
    ]
