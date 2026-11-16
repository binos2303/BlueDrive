from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("files", "0015_alter_uploadsession_state")]

    operations = [
        migrations.AddField(
            model_name="storagelocation",
            name="provider_version_id",
            field=models.CharField(blank=True, default="", max_length=1024),
        ),
    ]
