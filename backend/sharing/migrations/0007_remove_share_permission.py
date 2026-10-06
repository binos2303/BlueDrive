from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("sharing", "0006_alter_share_permission_label"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="share",
            name="permission",
        ),
    ]
