"""Giới hạn Storage Cluster mới vào SeaweedFS qua S3 API."""
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("infrastructure", "0007_runtime_connection_qualification")]

    operations = [
        migrations.AlterField(
            model_name="storagecluster", name="provider",
            field=models.CharField(
                max_length=16, choices=[("s3", "SeaweedFS (S3 API)")],
                default="s3",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="storagecluster", name="scc_cluster_provider_valid",
        ),
        migrations.AddConstraint(
            model_name="storagecluster",
            constraint=models.CheckConstraint(
                condition=Q(provider="s3"), name="scc_cluster_provider_valid",
            ),
        ),
    ]
