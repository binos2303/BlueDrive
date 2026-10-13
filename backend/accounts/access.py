from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden

from .models import Membership, Tenant


class ActiveTenantRequired(PermissionDenied):
    pass


def active_membership(user, tenant_id):
    if not user or not user.is_authenticated or not user.is_active:
        return None
    return (
        Membership.objects.filter(
            user_id=user.pk,
            tenant_id=tenant_id,
            status=Membership.Status.ACTIVE,
            tenant__status=Tenant.Status.ACTIVE,
        )
        .select_related("tenant")
        .first()
    )


def active_memberships(user):
    if not user or not user.is_authenticated or not user.is_active:
        return Membership.objects.none()
    return Membership.objects.filter(
        user_id=user.pk,
        status=Membership.Status.ACTIVE,
        tenant__status=Tenant.Status.ACTIVE,
    )


def has_active_membership(user):
    return active_memberships(user).exists()


def active_tenant_ids(user):
    return active_memberships(user).values("tenant_id")


def get_default_tenant(user):
    if not user or not user.is_authenticated or not user.is_active:
        raise ActiveTenantRequired("An active account is required.")

    business_memberships = list(
        Membership.objects.filter(
            user=user,
            status=Membership.Status.ACTIVE,
            tenant__kind=Tenant.Kind.BUSINESS,
            tenant__status=Tenant.Status.ACTIVE,
        ).select_related("tenant")[:2]
    )
    if len(business_memberships) > 1:
        raise ActiveTenantRequired(
            "Select an active business workspace before creating resources."
        )
    if business_memberships:
        return business_memberships[0].tenant

    membership = (
        Membership.objects.filter(
            user=user,
            tenant__kind=Tenant.Kind.PERSONAL,
            tenant__personal_owner_id=user.pk,
            status=Membership.Status.ACTIVE,
            tenant__status=Tenant.Status.ACTIVE,
        )
        .select_related("tenant")
        .first()
    )
    if membership is None:
        raise ActiveTenantRequired("No active workspace is available.")
    return membership.tenant


def active_tenant_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not has_active_membership(request.user):
            return HttpResponseForbidden("An active workspace membership is required.")
        return view_func(request, *args, **kwargs)

    return wrapped


def can_access_tenant_resource(user, tenant_id):
    return active_membership(user, tenant_id) is not None
