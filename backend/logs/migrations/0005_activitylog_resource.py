from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("logs", "0004_alter_activitylog_options_alter_activitylog_action"),
    ]

    operations = [
        migrations.AddField(
            model_name="activitylog",
            name="content_type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="activity_logs",
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddField(
            model_name="activitylog",
            name="object_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
    ]
