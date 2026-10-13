import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("files", "0011_add_tenant_composite_foreign_keys")]

    operations = [
        migrations.AddField("uploadsession", "object_key", models.CharField(blank=True, max_length=512)),
        migrations.AddField("uploadsession", "final_object_key", models.CharField(blank=True, max_length=512)),
        migrations.AddField("uploadsession", "provider_upload_id", models.CharField(blank=True, max_length=512)),
        migrations.AddField("uploadsession", "idempotency_key", models.CharField(blank=True, max_length=128)),
        migrations.AddField("uploadsession", "part_manifest", models.JSONField(blank=True, default=list)),
        migrations.AddConstraint(model_name="uploadsession", constraint=models.UniqueConstraint(condition=models.Q(("idempotency_key", ""), _negated=True), fields=("tenant", "initiated_by", "idempotency_key"), name="upload_idempotency_key_uniq")),
        migrations.RemoveConstraint(model_name="uploadsession", name="upload_state_valid_check"),
        migrations.AddConstraint(
            model_name="uploadsession",
            constraint=models.CheckConstraint(condition=models.Q(state__in=["initiated", "uploading", "verifying", "scanning", "available", "completed", "failed", "canceled", "expired"]), name="upload_state_valid_check"),
        ),
        migrations.CreateModel(
            name="UploadFinalizationJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("state", models.CharField(choices=[("pending", "Pending"), ("processing", "Processing"), ("done", "Done"), ("failed", "Failed")], default="pending", max_length=16)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("upload_session", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="finalization_job", to="files.uploadsession")),
            ],
        ),
    ]
