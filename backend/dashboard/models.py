from django.conf import settings
from django.db import models
from django.db.models import Q


class StarredItem(models.Model):
    """A user's personal Starred shortcut to a single file or folder."""

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.PROTECT,
        related_name="starred_items",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="starred_items",
    )
    file = models.ForeignKey(
        "files.File",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="starred_items",
    )
    folder = models.ForeignKey(
        "folders.Folder",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="starred_items",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(file__isnull=False, folder__isnull=True)
                    | Q(file__isnull=True, folder__isnull=False)
                ),
                name="starred_requires_one_item",
            ),
            models.UniqueConstraint(
                fields=["user", "file"],
                condition=Q(file__isnull=False),
                name="starred_user_file_uniq",
            ),
            models.UniqueConstraint(
                fields=["user", "folder"],
                condition=Q(folder__isnull=False),
                name="starred_user_folder_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "id"],
                name="starred_tenant_id_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "user", "created_at"], name="starred_tenant_usr_created_idx"),
        ]

    def __str__(self):
        target = self.file or self.folder
        return f"{self.user_id}: {target}"
