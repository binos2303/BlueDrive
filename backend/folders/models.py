from django.db import models
from django.contrib.auth.models import User
from django.db.models.functions import Lower


class Folder(models.Model):

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.PROTECT,
        related_name="folders",
    )

    workspace = models.ForeignKey(
        "accounts.Workspace",
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
                models.F("workspace"),
                Lower("folder_name"),
                condition=models.Q(("parent__isnull", True), ("deleted_at__isnull", True)),
                name="folder_live_root_name_uniq",
            ),
            models.UniqueConstraint(
                models.F("workspace"),
                models.F("parent"),
                Lower("folder_name"),
                condition=models.Q(("parent__isnull", False), ("deleted_at__isnull", True)),
                name="folder_live_child_name_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "id"],
                name="folder_tenant_id_uniq",
            ),
            models.UniqueConstraint(
                fields=["workspace", "id"],
                name="folder_workspace_id_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "parent", "deleted_at"],
                name="folder_tenant_parent_del_idx",
            ),
            models.Index(
                fields=["workspace", "parent", "deleted_at"],
                name="folder_ws_parent_del_idx",
            ),
            models.Index(
                fields=["tenant", "owner", "deleted_at"],
                name="folder_tenant_owner_del_idx",
            ),
            models.Index(
                fields=["workspace", "owner", "deleted_at"],
                name="folder_ws_owner_del_idx",
            ),
            models.Index(
                fields=["tenant", "purge_after"],
                condition=models.Q(deleted_at__isnull=False),
                name="folder_purge_after_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        # Existing callers may omit workspace. Nested folders inherit the
        # parent's workspace; root folders use the tenant's default workspace.
        if self.workspace_id is None and self.tenant_id:
            if self.parent_id:
                self.workspace_id = type(self).objects.filter(
                    pk=self.parent_id
                ).values_list("workspace_id", flat=True).first()
            if self.workspace_id is None:
                from accounts.models import Tenant
                from accounts.access import get_default_workspace
                tenant = Tenant.objects.get(pk=self.tenant_id)
                self.workspace_id = get_default_workspace(tenant).pk
        super().save(*args, **kwargs)

    def __str__(self):
        return self.folder_name