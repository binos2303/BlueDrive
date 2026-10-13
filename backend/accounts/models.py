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
