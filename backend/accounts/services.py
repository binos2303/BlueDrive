from django.db import transaction

from accounts.models import Membership, QuotaAccount, Tenant


@transaction.atomic
def get_personal_tenant(user):
    if not getattr(user, "is_authenticated", False) or user.pk is None:
        raise ValueError("A saved authenticated user is required.")

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
    
    QuotaAccount.objects.get_or_create(
        tenant=tenant,
        scope=QuotaAccount.Scope.TENANT,
        defaults={
            "limit_bytes": 10 * 1024 * 1024,
            "used_bytes": 0,
            "reserved_bytes": 0,
        },
    )

    return tenant
