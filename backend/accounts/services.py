from django.db import transaction

from accounts.models import Membership, OrganizationIdentity, QuotaAccount, StoragePlan, Tenant, Workspace, WorkspaceMembership
from accounts.access import get_default_workspace
from accounts.platform_admin import is_platform_admin


def starting_storage_plan(scope):
    """Read the currently configured baseline preset for new allocations.

    This is deliberately strict: a missing/inactive baseline must not silently
    allocate unlimited storage or a second hard-coded quota value.
    """
    plan_code = {
        StoragePlan.Scope.PERSONAL: "free",
        StoragePlan.Scope.WORKSPACE: "workspace-starter",
    }.get(scope)
    if plan_code is None:
        raise ValueError("Unsupported starting storage scope.")
    try:
        return StoragePlan.objects.get(code=plan_code, scope=scope, is_active=True)
    except StoragePlan.DoesNotExist as exc:
        raise RuntimeError(
            f"Required baseline storage plan '{plan_code}' is missing or inactive. "
            "Check Storage Plans before provisioning new storage."
        ) from exc


@transaction.atomic
def get_personal_tenant(user):
    if not getattr(user, "is_authenticated", False) or user.pk is None:
        raise ValueError("A saved authenticated user is required.")

    if user.is_staff or user.is_superuser or is_platform_admin(user):
        raise PermissionError("Platform administrators cannot provision personal drives.")
    if OrganizationIdentity.objects.filter(user_id=user.pk).exists():
        raise PermissionError("Organization-managed accounts cannot provision personal drives.")

    tenant, _ = Tenant.objects.get_or_create(
        personal_owner=user,
        defaults={
            "kind": Tenant.Kind.PERSONAL,
            "name": f"{user.get_username()}'s Drive"[:255],
            "status": Tenant.Status.ACTIVE,
        },
    )
    Membership.objects.get_or_create(
        tenant=tenant,
        user=user,
        defaults={
            "role": Membership.Role.OWNER,
            "status": Membership.Status.ACTIVE,
        },
    )
    
    workspace = get_default_workspace(tenant)
    WorkspaceMembership.objects.get_or_create(
        workspace=workspace,
        membership=Membership.objects.get(tenant=tenant, user=user),
        defaults={
            "role": WorkspaceMembership.Role.ADMIN,
            "status": WorkspaceMembership.Status.ACTIVE,
        },
    )

    # Resolve the plan only when an allocation is missing; returning users
    # keep their previously assigned plan and storage limit unchanged.
    if not QuotaAccount.objects.filter(tenant=tenant, scope=QuotaAccount.Scope.TENANT).exists():
        plan = starting_storage_plan(StoragePlan.Scope.PERSONAL)
        QuotaAccount.objects.get_or_create(
            tenant=tenant,
            scope=QuotaAccount.Scope.TENANT,
            defaults={
                "plan": plan,
                "limit_bytes": plan.limit_bytes,
                "used_bytes": 0,
                "reserved_bytes": 0,
            },
        )

    return tenant


@transaction.atomic
def provision_organization_drive(identity):
    """Cấp ngăn riêng trước activation; không mượn quota/cấu hình storage Personal."""
    identity = OrganizationIdentity.objects.select_for_update().select_related("tenant", "user").get(pk=identity.pk)
    identity.clean()
    existing = Workspace.objects.filter(owned_identity=identity).first()
    if existing is not None:
        return existing
    slug = f"my-drive-{identity.user_id}"
    if Workspace.objects.filter(tenant=identity.tenant, slug=slug).exists():
        raise ValueError("My Drive slug conflicts with an existing workspace.")
    return Workspace.objects.create(
        tenant=identity.tenant, owned_identity=identity, name="My Drive", slug=slug,
        is_default=False, created_by=identity.invited_by,
    )
