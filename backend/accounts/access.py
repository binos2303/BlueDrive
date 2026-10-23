from functools import wraps
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpResponseForbidden

from .models import (
    Membership, Tenant, Workspace, WorkspaceGroupAccess,
    WorkspaceMembership,
)


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
    """Resolve the personal My Drive tenant first, independent of memberships.

    The Drive switcher sends an explicit workspace ID when a shared workspace
    is selected. Without that selector, Drive means the authenticated user's
    own personal area; this prevents joining a shared/business workspace from
    silently replacing My Drive as the default context.
    """
    if not user or not user.is_authenticated or not user.is_active:
        raise ActiveTenantRequired("An active account is required.")

    personal_membership = (
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
    if personal_membership is not None:
        return personal_membership.tenant

    # Preserve compatibility for older installations without a personal tenant.
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
            "Select an active organization before creating resources."
        )
    if business_memberships:
        return business_memberships[0].tenant
    raise ActiveTenantRequired("No active personal drive is available.")


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


WORKSPACE_ROLE_RANK = {
    WorkspaceMembership.Role.VIEWER: 1,
    WorkspaceMembership.Role.EDITOR: 2,
    WorkspaceMembership.Role.ADMIN: 3,
}


def get_default_workspace(tenant):
    """Return the tenant's default workspace, creating one if necessary."""
    workspace = Workspace.objects.filter(tenant=tenant, is_default=True).first()
    if workspace is not None:
        return workspace

    # Avoid colliding with a user-created workspace whose slug is "general".
    base = "general"
    candidate = base
    suffix = 2
    while Workspace.objects.filter(tenant=tenant, slug=candidate).exists():
        ending = f"-{suffix}"
        candidate = f"{base[:100 - len(ending)]}{ending}"
        suffix += 1

    try:
        # A savepoint allows a concurrent insert conflict to be handled even
        # when the caller is already inside a larger atomic transaction.
        with transaction.atomic():
            return Workspace.objects.create(
                tenant=tenant,
                name="General",
                slug=candidate,
                status=Workspace.Status.ACTIVE,
                is_default=True,
            )
    except IntegrityError:
        workspace = Workspace.objects.filter(tenant=tenant, is_default=True).first()
        if workspace is not None:
            return workspace
        raise


def workspace_role_for_user(user, workspace):
    """Resolve the strongest active workspace role for a tenant member.

    Tenant owners/admins can administer all active workspaces in their tenant.
    Other users need a direct workspace membership or a grant through a group.
    This function resolves workspace membership; resource visibility and mutations
    must also apply the existing file-owner/share checks.
    """
    membership = active_membership(user, workspace.tenant_id)
    if membership is None or workspace.status != Workspace.Status.ACTIVE:
        return None
    if membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN):
        return WorkspaceMembership.Role.ADMIN

    roles = list(
        WorkspaceMembership.objects.filter(
            workspace=workspace,
            membership=membership,
            status=WorkspaceMembership.Status.ACTIVE,
        ).values_list("role", flat=True)
    )
    roles.extend(
        WorkspaceGroupAccess.objects.filter(
            workspace=workspace,
            group__tenant_id=workspace.tenant_id,
            group__status="active",
            group__member_assignments__membership=membership,
        ).values_list("role", flat=True)
    )
    if not roles:
        return None
    return max(roles, key=lambda role: WORKSPACE_ROLE_RANK.get(role, 0))


def can_access_workspace(user, workspace):
    return workspace_role_for_user(user, workspace) is not None


def can_manage_workspace(user, workspace):
    return workspace_role_for_user(user, workspace) == WorkspaceMembership.Role.ADMIN


def can_edit_workspace_content(user, workspace):
    """Return whether ``user`` has Editor or Admin access to ``workspace``."""
    role = workspace_role_for_user(user, workspace)
    return WORKSPACE_ROLE_RANK.get(role, 0) >= WORKSPACE_ROLE_RANK[WorkspaceMembership.Role.EDITOR]


def _request_workspace_values(request, payload=None):
    """Collect non-empty workspace selectors supplied by supported clients."""
    values = []

    if isinstance(payload, dict) and "workspace_id" in payload:
        value = payload.get("workspace_id")
        if value is not None and str(value).strip():
            values.append(value)

    for params in (getattr(request, "GET", None), getattr(request, "POST", None)):
        if params is not None and "workspace_id" in params:
            value = params.get("workspace_id")
            if value is not None and str(value).strip():
                values.append(value)

    headers = getattr(request, "headers", {})
    header_value = headers.get("X-Workspace-ID") if headers else None
    if not header_value:
        header_value = getattr(request, "META", {}).get("HTTP_X_WORKSPACE_ID")
    if header_value is not None and str(header_value).strip():
        values.append(header_value)

    return values


def resolve_request_workspace(request, tenant, payload=None):
    """Resolve one active workspace that the caller is authorized to access.

    Supported selectors are JSON/form/query ``workspace_id`` and the
    ``X-Workspace-ID`` header. Conflicting or malformed selectors fail closed.
    Requests without a selector retain compatibility by selecting the tenant's
    default workspace when accessible, otherwise the first accessible active
    workspace. An explicitly selected workspace never silently falls back.
    """
    if tenant is None:
        return None

    tenant_id = getattr(tenant, "pk", tenant)
    tenant_obj = tenant if isinstance(tenant, Tenant) else Tenant.objects.filter(pk=tenant_id).first()
    if tenant_obj is None or tenant_obj.status != Tenant.Status.ACTIVE:
        return None

    supplied_values = _request_workspace_values(request, payload)
    selected_workspace_id = None
    if supplied_values:
        parsed_ids = []
        for value in supplied_values:
            try:
                parsed_ids.append(UUID(str(value).strip()))
            except (TypeError, ValueError, AttributeError):
                return None
        # Reject disagreement between body, query/form, and header rather than
        # letting different layers authorize different workspace contexts.
        if len(set(parsed_ids)) != 1:
            return None
        selected_workspace_id = parsed_ids[0]

    if selected_workspace_id is not None:
        # A user's selected workspace may belong to another personal tenant or
        # organization. The workspace UUID selects the context; membership and
        # role checks, not the user's My Drive tenant, authorize access.
        workspace = Workspace.objects.filter(
            pk=selected_workspace_id,
            tenant__status=Tenant.Status.ACTIVE,
            status=Workspace.Status.ACTIVE,
        ).select_related("tenant").first()
        if workspace is None or not can_access_workspace(request.user, workspace):
            return None
        return workspace

    default_workspace = get_default_workspace(tenant_obj)
    if (
        default_workspace.status == Workspace.Status.ACTIVE
        and can_access_workspace(request.user, default_workspace)
    ):
        return default_workspace

    # A regular member may only have access to a non-default workspace.
    for workspace in Workspace.objects.filter(
        tenant=tenant_obj,
        status=Workspace.Status.ACTIVE,
    ).order_by("name", "id"):
        if can_access_workspace(request.user, workspace):
            return workspace
    return None

