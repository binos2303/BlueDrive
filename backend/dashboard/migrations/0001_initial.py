from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0003_quotaaccount_quota_tenant_id_uniq"),
        ("files", "0013_fileversion_quarantined_state"),
        ("folders", "0009_alter_folder_tenant"),
    ]

    operations = [
        migrations.CreateModel(
            name="StarredItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("file", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="starred_items", to="files.file")),
                ("folder", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="starred_items", to="folders.folder")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="starred_items", to="accounts.tenant")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="starred_items", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="starreditem",
            constraint=models.CheckConstraint(condition=(models.Q(("file__isnull", False), ("folder__isnull", True)) | models.Q(("file__isnull", True), ("folder__isnull", False))), name="starred_requires_one_item"),
        ),
        migrations.AddConstraint(
            model_name="starreditem",
            constraint=models.UniqueConstraint(condition=models.Q(("file__isnull", False)), fields=("user", "file"), name="starred_user_file_uniq"),
        ),
        migrations.AddConstraint(
            model_name="starreditem",
            constraint=models.UniqueConstraint(condition=models.Q(("folder__isnull", False)), fields=("user", "folder"), name="starred_user_folder_uniq"),
        ),
        migrations.AddConstraint(
            model_name="starreditem",
            constraint=models.UniqueConstraint(fields=("tenant", "id"), name="starred_tenant_id_uniq"),
        ),
        migrations.AddIndex(
            model_name="starreditem",
            index=models.Index(fields=["tenant", "user", "created_at"], name="starred_tenant_usr_created_idx"),
        ),
    ]
