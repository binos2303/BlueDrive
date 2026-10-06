from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("folders", "0004_folder_deleted_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="folder",
            name="last_accessed_at",
            field=models.DateTimeField(blank=True, null=True, editable=False),
        ),
    ]
