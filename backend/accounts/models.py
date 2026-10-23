import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class Tenant(models.Model):
    class Kind(models.TextChoices):
        PERSONAL = "personal", "Personal"
        BUSINESS = "business", "Business"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        DELETION_PENDING = "deletion_pending", "Deletion pending"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, null=True, blank=True, unique=True)
    personal_owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="personal_tenant",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="personal", personal_owner__isnull=False)
                    | Q(kind="business", personal_owner__isnull=True)
                ),
                name="tenant_kind_personal_owner_check",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=["active", "suspended", "deletion_pending"]
                ),
                name="tenant_status_valid_check",
            ),
        ]
        indexes = [
            models.Index(fields=["kind", "status"], name="tenant_kind_status_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INVITED = "invited", "Invited"
        SUSPENDED = "suspended", "Suspended"
        REVOKED = "revoked", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tenant_memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "user"],
                name="membership_tenant_user_uniq",
            ),
            models.CheckConstraint(
                condition=Q(role__in=["owner", "admin", "member"]),
                name="membership_role_valid_check",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=["active", "invited", "suspended", "revoked"]
                ),
                name="membership_status_valid_check",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"], name="membership_user_status_idx"),
            models.Index(
                fields=["tenant", "status", "role"],
                name="membership_tenant_role_idx",
            ),
        ]


class QuotaAccount(models.Model):
    class Scope(models.TextChoices):
        TENANT = "tenant", "Tenant"
        MEMBER = "member", "Member"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="quota_accounts",
    )
    scope = models.CharField(max_length=16, choices=Scope.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="member_quota_accounts",
    )
    limit_bytes = models.BigIntegerField(null=True, blank=True)
    used_bytes = models.BigIntegerField(default=0)
    reserved_bytes = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(scope="tenant", user__isnull=True)
                    | Q(scope="member", user__isnull=False)
                ),
                name="quota_scope_user_check",
            ),
            models.CheckConstraint(
                condition=Q(limit_bytes__isnull=True) | Q(limit_bytes__gte=0),
                name="quota_limit_nonnegative_check",
            ),
            models.CheckConstraint(
                condition=Q(used_bytes__gte=0),
                name="quota_used_nonnegative_check",
            ),
            models.CheckConstraint(
                condition=Q(reserved_bytes__gte=0),
                name="quota_reserved_nonnegative_check",
            ),
            models.UniqueConstraint(
                fields=["tenant"],
                condition=Q(scope="tenant"),
                name="quota_tenant_scope_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "id"],
                name="quota_tenant_id_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "user"],
                condition=Q(scope="member"),
                name="quota_member_scope_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "user"], name="quota_tenant_user_idx"),
        ]


class Workspace(models.Model):
    """A collaboration area contained within one tenant."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="workspaces",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    default_member_role = models.CharField(
        max_length=16,
        choices=(("viewer", "Viewer"), ("editor", "Editor")),
        default="viewer",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    is_default = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_workspaces",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "slug"],
                name="workspace_tenant_slug_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "id"],
                name="workspace_tenant_id_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant"],
                condition=Q(is_default=True),
                name="workspace_one_default_per_tenant",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["active", "archived"]),
                name="workspace_status_valid_check",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="workspace_tenant_status_idx"),
        ]
        ordering = ["name", "id"]

    def __str__(self):
        return f"{self.tenant.name} / {self.name}"


class Group(models.Model):
    """An organization-scoped set of tenant memberships."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="groups",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_tenant_groups",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                models.F("tenant"),
                Lower("name"),
                name="group_tenant_name_ci_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "id"],
                name="group_tenant_id_uniq",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["active", "archived"]),
                name="group_status_valid_check",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="group_tenant_status_idx"),
        ]
        ordering = ["name", "id"]

    def __str__(self):
        return f"{self.tenant.name} / {self.name}"


class WorkspaceMembership(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Workspace admin"
        EDITOR = "editor", "Editor"
        VIEWER = "viewer", "Viewer"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="member_assignments",
    )
    membership = models.ForeignKey(
        Membership,
        on_delete=models.CASCADE,
        related_name="workspace_assignments",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_workspace_memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "membership"],
                name="workspace_member_pair_uniq",
            ),
            models.UniqueConstraint(
                fields=["workspace", "id"],
                name="workspace_member_id_uniq",
            ),
            models.CheckConstraint(
                condition=Q(role__in=["admin", "editor", "viewer"]),
                name="workspace_member_role_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["active", "revoked"]),
                name="workspace_member_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "status", "role"], name="workspace_member_role_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.workspace_id and self.membership_id:
            workspace_tenant_id = Workspace.objects.filter(pk=self.workspace_id).values_list("tenant_id", flat=True).first()
            membership_tenant_id = Membership.objects.filter(pk=self.membership_id).values_list("tenant_id", flat=True).first()
            if workspace_tenant_id is not None and membership_tenant_id is not None and workspace_tenant_id != membership_tenant_id:
                from django.core.exceptions import ValidationError
                raise ValidationError("Workspace and member must belong to the same tenant.")
        super().save(*args, **kwargs)


class GroupMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="member_assignments",
    )
    membership = models.ForeignKey(
        Membership,
        on_delete=models.CASCADE,
        related_name="group_assignments",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_group_memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["group", "membership"],
                name="group_member_pair_uniq",
            ),
            models.UniqueConstraint(
                fields=["group", "id"],
                name="group_member_id_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["group", "membership"], name="group_membership_lookup_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.group_id and self.membership_id:
            group_tenant_id = Group.objects.filter(pk=self.group_id).values_list("tenant_id", flat=True).first()
            membership_tenant_id = Membership.objects.filter(pk=self.membership_id).values_list("tenant_id", flat=True).first()
            if group_tenant_id is not None and membership_tenant_id is not None and group_tenant_id != membership_tenant_id:
                from django.core.exceptions import ValidationError
                raise ValidationError("Group and member must belong to the same tenant.")
        super().save(*args, **kwargs)


class WorkspaceGroupAccess(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Workspace admin"
        EDITOR = "editor", "Editor"
        VIEWER = "viewer", "Viewer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="group_access_grants",
    )
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="workspace_access_grants",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_workspace_group_grants",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "group"],
                name="workspace_group_pair_uniq",
            ),
            models.CheckConstraint(
                condition=Q(role__in=["admin", "editor", "viewer"]),
                name="workspace_group_role_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "role"], name="workspace_group_role_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.workspace_id and self.group_id:
            workspace_tenant_id = Workspace.objects.filter(pk=self.workspace_id).values_list("tenant_id", flat=True).first()
            group_tenant_id = Group.objects.filter(pk=self.group_id).values_list("tenant_id", flat=True).first()
            if workspace_tenant_id is not None and group_tenant_id is not None and workspace_tenant_id != group_tenant_id:
                from django.core.exceptions import ValidationError
                raise ValidationError("Workspace and group must belong to the same tenant.")
        super().save(*args, **kwargs)


class WorkspaceInvite(models.Model):
    """Single-use, expiring invitation to join one workspace."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="invites",
    )
    email = models.EmailField(max_length=254)
    token_hash = models.CharField(max_length=64, unique=True)
    role = models.CharField(
        max_length=16,
        choices=(("viewer", "Viewer"), ("editor", "Editor")),
        default="viewer",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_workspace_invites",
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(role__in=["viewer", "editor"]),
                name="workspace_invite_role_valid",
            ),
            models.UniqueConstraint(
                fields=["workspace", "email"],
                condition=Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="workspace_invite_pending_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "email"], name="workspace_invite_email_idx"),
            models.Index(fields=["expires_at"], name="workspace_invite_expiry_idx"),
        ]

    def __str__(self):
        return f"Invitation to {self.workspace.name} for {self.email}"
