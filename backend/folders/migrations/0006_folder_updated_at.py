from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ("folders", "0005_folder_last_accessed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="folder",
            name="updated_at",
            field=models.DateTimeField(default=timezone.now),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="folder",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
    ]
