from django.db import transaction

from accounts.models import Membership, QuotaAccount, StoragePlan, Tenant, WorkspaceMembership
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
