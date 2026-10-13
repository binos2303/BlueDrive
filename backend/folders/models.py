from django.db import models
from django.contrib.auth.models import User
from django.db.models.functions import Lower


class Folder(models.Model):

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.PROTECT,
        related_name="folders",
    )

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    folder_name = models.CharField(
        max_length=255
    )

    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    last_accessed_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )

    deleted_at = models.DateTimeField(
        null=True,
        blank=True
    )
    purge_after = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                models.F("tenant"),
                Lower("folder_name"),
                condition=models.Q(parent__isnull=True, deleted_at__isnull=True),
                name="folder_live_root_name_uniq",
            ),
            models.UniqueConstraint(
                models.F("tenant"),
                models.F("parent"),
                Lower("folder_name"),
                condition=models.Q(parent__isnull=False, deleted_at__isnull=True),
                name="folder_live_child_name_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "id"],
                name="folder_tenant_id_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "parent", "deleted_at"],
                name="folder_tenant_parent_del_idx",
            ),
            models.Index(
                fields=["tenant", "owner", "deleted_at"],
                name="folder_tenant_owner_del_idx",
            ),
            models.Index(
                fields=["tenant", "purge_after"],
                condition=models.Q(deleted_at__isnull=False),
                name="folder_purge_after_idx",
            ),
        ]

    def __str__(self):
        return self.folder_name