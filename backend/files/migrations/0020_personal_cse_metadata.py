from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("files", "0019_file_purge_intent")]
    operations = [
        migrations.AddField("fileversion", "cse_metadata", models.JSONField(blank=True, default=dict)),
        migrations.AddField("fileversion", "crypto_version_id",
                            models.UUIDField(blank=True, editable=False, null=True, unique=True)),
        migrations.AddField("uploadsession", "cse_metadata", models.JSONField(blank=True, default=dict)),
        migrations.AddField("uploadsession", "crypto_version_id",
                            models.UUIDField(blank=True, editable=False, null=True, unique=True)),
    ]
