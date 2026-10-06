from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sharing", "0005_alter_share_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="share",
            name="permission",
            field=models.CharField(
                choices=[("read", "View"), ("download", "Download")],
                default="read",
                max_length=20,
            ),
        ),
    ]
