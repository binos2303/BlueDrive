from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("files", "0012_uploadsession_s3_multipart_fields")]

    operations = [
        migrations.AlterField(
            model_name="fileversion",
            name="state",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("uploading", "Uploading"),
                    ("verifying", "Verifying"),
                    ("scanning", "Scanning"),
                    ("available", "Available"),
                    ("quarantined", "Quarantined"),
                    ("failed", "Failed"),
                    ("deleting", "Deleting"),
                    ("deleted", "Deleted"),
                ],
                max_length=20,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="fileversion",
            name="file_version_state_valid_check",
        ),
        migrations.AddConstraint(
            model_name="fileversion",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    state__in=[
                        "pending",
                        "uploading",
                        "verifying",
                        "scanning",
                        "available",
                        "quarantined",
                        "failed",
                        "deleting",
                        "deleted",
                    ]
                ),
                name="file_version_state_valid_check",
            ),
        ),
    ]
