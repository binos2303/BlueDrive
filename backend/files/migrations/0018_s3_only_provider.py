"""Giới hạn metadata lưu trữ của BlueDrive vào S3 API (SeaweedFS)."""
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("files", "0017_pin_storage_targets")]

    operations = [
        migrations.AlterField(
            model_name="storageconfig", name="provider",
            field=models.CharField(
                max_length=16, choices=[("s3", "SeaweedFS (S3 API)")],
            ),
        ),
        migrations.RemoveConstraint(
            model_name="storageconfig", name="storage_provider_valid_check",
        ),
        migrations.AddConstraint(
            model_name="storageconfig",
            constraint=models.CheckConstraint(
                condition=Q(provider="s3"), name="storage_provider_valid_check",
            ),
        ),
    ]
