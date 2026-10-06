from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("files", "0005_file_dek_nonce_file_updated_at_file_wrapped_dek_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="file",
            name="last_accessed_at",
            field=models.DateTimeField(blank=True, null=True, editable=False),
        ),
    ]
