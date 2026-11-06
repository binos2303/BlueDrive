import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


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
        WORKSPACE = "workspace", "Workspace"

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
    workspace = models.ForeignKey(
        "accounts.Workspace", null=True, blank=True, on_delete=models.PROTECT,
        related_name="quota_accounts",
    )
    plan = models.ForeignKey(
        "accounts.StoragePlan", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assignments",
    )
    used_bytes = models.BigIntegerField(default=0)
    reserved_bytes = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(scope="tenant", user__isnull=True, workspace__isnull=True)
                    | Q(scope="member", user__isnull=False, workspace__isnull=True)
                    | Q(scope="workspace", user__isnull=True, workspace__isnull=False)
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
                fields=["workspace"],
                condition=Q(scope="workspace"),
                name="quota_workspace_uniq",
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


class TrackedAccountSession(models.Model):
    """Authenticated database sessions observed after deploying tracking.

    Django's session row remains the source of truth. No session token is exposed
    by administrative APIs; an unrelated UUID identifies a row for revocation.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.OneToOneField(
        "sessions.Session", on_delete=models.CASCADE, related_name="account_tracking"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tracked_sessions"
    )
    started_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-last_seen_at"], name="acct_session_usr_seen_idx"),
        ]


class PlatformAdminAuditEvent(models.Model):
    """Append-only through the platform administration API.

    No edit/delete endpoint is provided. Database administrators must enforce
    retention/immutability separately for higher assurance.
    """

    class Action(models.TextChoices):
        SUSPEND = "user.suspend", "Suspend account"
        REACTIVATE = "user.reactivate", "Reactivate account"
        REVOKE_SESSION = "session.revoke", "Revoke session"
        INVITE_ADMIN = "admin.invite", "Invite administrator"
        ACCEPT_ADMIN = "admin.accept", "Accept administrator invitation"
        DISABLE_ADMIN = "admin.disable", "Disable administrator"
        FILE_TRASH = "file.trash", "Move file to Trash"
        FILE_RESTORE = "file.restore", "Restore file"
        FILE_PURGE_REQUESTED = "file.purge.requested", "Request file purge"
        FILE_PURGE_SUCCEEDED = "file.purge.succeeded", "Complete file purge"
        FILE_PURGE_FAILED = "file.purge.failed", "File purge failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="platform_audit_actions"
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="platform_audit_targets"
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    reason = models.CharField(max_length=500)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["-created_at"], name="platform_audit_created_idx"),
            models.Index(fields=["target_user", "-created_at"], name="platform_audit_target_idx"),
        ]
        ordering = ["-created_at"]


class PlatformAdminIdentity(models.Model):
    """Dedicated non-superuser administrators; never shares a personal Drive identity.

    Existing Django staff superusers remain bootstrap Super Admins. Standard
    Platform Admins must have an ACTIVE identity in addition to is_staff=True.
    """

    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, primary_key=True, on_delete=models.PROTECT,
        related_name="platform_admin_identity",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.INVITED)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="platform_admin_invitations_created",
    )
    invited_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Dedicated Platform Administrator"
        verbose_name_plural = "Dedicated Platform Administrators"


class StoragePlan(models.Model):
    """Allocation preset size only; not a subscription or payment record."""
    class Scope(models.TextChoices):
        PERSONAL = "personal", "Personal Drive"
        WORKSPACE = "workspace", "Workspace"

    code = models.SlugField(max_length=48, primary_key=True)
    name = models.CharField(max_length=80)
    scope = models.CharField(max_length=16, choices=Scope.choices)
    limit_bytes = models.BigIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(limit_bytes__gte=0), name="storage_plan_limit_nonneg")]
        ordering = ["scope", "limit_bytes", "code"]


class QuotaAuditEvent(models.Model):
    """Append-only quota allocation history, restricted to platform administrators."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    quota_account = models.ForeignKey("accounts.QuotaAccount", on_delete=models.PROTECT, related_name="audit_events")
    old_limit_bytes = models.BigIntegerField(null=True)
    new_limit_bytes = models.BigIntegerField(null=True)
    old_plan_code = models.CharField(max_length=48, blank=True)
    new_plan_code = models.CharField(max_length=48, blank=True)
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["quota_account", "created_at"], name="quota_audit_account_dt_idx")]


class StoragePlanAuditEvent(models.Model):
    """Append-only record for storage plan definitions (not account allocation)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    plan_code = models.CharField(max_length=48)
    action = models.CharField(max_length=16)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class StoragePolicy(models.Model):
    """Provider policy for quota warnings and personal email-based file shares.

    NULL means no file-size restriction. Organization-owned storage has its
    own administration scope and is not constrained by this global policy.
    """
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    max_personal_file_bytes = models.BigIntegerField(null=True, blank=True)
    warning_percent = models.PositiveSmallIntegerField(default=80)
    critical_percent = models.PositiveSmallIntegerField(default=95)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(max_personal_file_bytes__isnull=True) | Q(max_personal_file_bytes__gte=0), name="direct_share_file_size_nonneg"),
            models.CheckConstraint(condition=Q(warning_percent__gte=1, warning_percent__lt=models.F("critical_percent"), critical_percent__lte=100), name="storage_policy_thresholds_valid"),
        ]


class StoragePolicyAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    old_limit = models.BigIntegerField(null=True, blank=True)
    new_limit = models.BigIntegerField(null=True, blank=True)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
