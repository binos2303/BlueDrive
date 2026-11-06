import uuid
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_storage_quota_scopes"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(name="StoragePlanAuditEvent", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("plan_code", models.CharField(max_length=48)),
            ("action", models.CharField(max_length=16)),
            ("before", models.JSONField(default=dict)),
            ("after", models.JSONField(default=dict)),
            ("reason", models.CharField(max_length=500)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["-created_at", "-id"]}),
        migrations.CreateModel(name="StoragePolicy", fields=[
            ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
            ("max_personal_file_bytes", models.BigIntegerField(blank=True, null=True)),
            ("warning_percent", models.PositiveSmallIntegerField(default=80)),
            ("critical_percent", models.PositiveSmallIntegerField(default=95)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ]),
        migrations.AddConstraint(model_name="storagepolicy", constraint=models.CheckConstraint(condition=Q(max_personal_file_bytes__isnull=True) | Q(max_personal_file_bytes__gte=0), name="direct_share_file_size_nonneg")),
        migrations.AddConstraint(model_name="storagepolicy", constraint=models.CheckConstraint(condition=Q(warning_percent__gte=1, warning_percent__lt=models.F("critical_percent"), critical_percent__lte=100), name="storage_policy_thresholds_valid")),
        migrations.CreateModel(name="StoragePolicyAuditEvent", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("old_limit", models.BigIntegerField(blank=True, null=True)),
            ("new_limit", models.BigIntegerField(blank=True, null=True)),
            ("before", models.JSONField(default=dict)),
            ("after", models.JSONField(default=dict)),
            ("reason", models.CharField(max_length=500)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["-created_at", "-id"]}),
    ]
