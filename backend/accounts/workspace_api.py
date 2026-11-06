"""Workspace lifecycle, invitations, activity, and organization administration.

Personal SaaS workspace endpoints coexist with organization-scoped management
APIs. Drive access remains enforced by the shared workspace and resource
permission services; selectors never grant access by themselves.
"""
from uuid import UUID
from datetime import timedelta
import hashlib
import secrets

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from logs.models import ActivityLog
from .access import (
    active_membership,
    can_access_workspace,
    can_manage_workspace,
    get_default_workspace,
    workspace_role_for_user,
)
from .models import (
    Membership,
    Tenant,
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
)
from .services import get_personal_tenant

ADMIN_ROLES = (Membership.Role.OWNER, Membership.Role.ADMIN)
WORKSPACE_ROLES = {choice for choice, _label in WorkspaceMembership.Role.choices}


def _tenant_context(request, tenant_id, *, require_admin=False):
    tenant = Tenant.objects.filter(
        pk=tenant_id,
        kind=Tenant.Kind.BUSINESS,
        status=Tenant.Status.ACTIVE,
    ).first()
    if tenant is None:
        return None, None, Response(
            {"detail": "Organization is unavailable."},
            status=status.HTTP_404_NOT_FOUND,
        )

    membership = active_membership(request.user, tenant.pk)
    if membership is None:
        return None, None, Response(
            {"detail": "Organization access is unavailable."},
            status=status.HTTP_404_NOT_FOUND,
        )
    if require_admin and membership.role not in ADMIN_ROLES:
        return None, None, Response(
            {"detail": "Organization administrator access is required."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return tenant, membership, None


def _workspace_context(request, tenant_id, workspace_id, *, require_manager=False):
    tenant, tenant_membership, error = _tenant_context(request, tenant_id)
    if error:
        return None, None, error
    workspace = Workspace.objects.filter(
        pk=workspace_id,
        tenant=tenant,
    ).first()
    if workspace is None:
        return None, None, Response(
            {"detail": "Workspace is unavailable."},
            status=status.HTTP_404_NOT_FOUND,
        )

    is_tenant_admin = tenant_membership.role in ADMIN_ROLES
    if require_manager and not is_tenant_admin and not can_manage_workspace(request.user, workspace):
        return None, None, Response(
            {"detail": "Workspace administrator access is required."},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not require_manager and not is_tenant_admin and not can_access_workspace(request.user, workspace):
        return None, None, Response(
            {"detail": "Workspace access is unavailable."},
            status=status.HTTP_404_NOT_FOUND,
        )
    return tenant, workspace, None


def _valid_uuid(value):
    try:
        UUID(str(value))
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def _slug_for_workspace(tenant, name):
    base = slugify(name)[:100] or "workspace"
    candidate = base
    suffix = 2
    while Workspace.objects.filter(tenant=tenant, slug=candidate).exists():
        ending = f"-{suffix}"
        candidate = f"{base[:100 - len(ending)]}{ending}"
        suffix += 1
    return candidate


def _audit(request, tenant, action, description, **metadata):
    workspace_id = metadata.get("workspace_id")
    workspace = None
    if workspace_id and _valid_uuid(workspace_id):
        workspace = Workspace.objects.filter(
            pk=workspace_id,
            tenant_id=tenant.pk,
        ).first()
    ActivityLog.objects.create(
        user=request.user,
        tenant=tenant,
        workspace=workspace,
        action=action,
        description=description[:500],
        metadata=metadata,
    )


def _serialize_workspace(workspace, user):
    role = None
    if user is not None:
        tenant_membership = active_membership(user, workspace.tenant_id)
        if tenant_membership and tenant_membership.role in ADMIN_ROLES:
            role = WorkspaceMembership.Role.ADMIN
        elif workspace.status == Workspace.Status.ACTIVE:
            role = workspace_role_for_user(user, workspace)

    creator = workspace.created_by
    if creator is None and workspace.tenant.kind == Tenant.Kind.PERSONAL:
        creator = workspace.tenant.personal_owner
    creator_label = creator.get_username() if creator else "Workspace owner"
    return {
        "id": str(workspace.pk),
        "tenantId": str(workspace.tenant_id),
        "tenantName": workspace.tenant.name,
        "tenantKind": workspace.tenant.kind,
        "name": workspace.name,
        "slug": workspace.slug,
        "description": workspace.description,
        "status": workspace.status,
        "isDefault": workspace.is_default,
        "defaultMemberRole": workspace.default_member_role,
        "currentUserRole": role,
        "canManage": bool(role == WorkspaceMembership.Role.ADMIN),
        "createdByUserId": creator.pk if creator else None,
        "createdByUsername": creator_label,
        "createdByInitials": "".join(part[0] for part in creator_label.split()[:2]).upper()[:2] or "W",
        "isOwnedByMe": bool(creator and creator.pk == user.pk),
        "memberCount": workspace.member_assignments.filter(
            status=WorkspaceMembership.Status.ACTIVE,
            membership__status=Membership.Status.ACTIVE,
        ).count(),
        "createdAt": workspace.created_at,
        "updatedAt": workspace.updated_at,
    }


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def organization_members_view(request, tenant_id):
    tenant, _actor_membership, error = _tenant_context(
        request, tenant_id, require_admin=True
    )
    if error:
        return error
    rows = Membership.objects.filter(tenant=tenant).select_related("user").order_by(
        "user__username", "id"
    )
    return Response({
        "members": [
            {
                "membershipId": str(row.pk),
                "userId": row.user_id,
                "username": row.user.get_username(),
                "email": row.user.email,
                "role": row.role,
                "status": row.status,
            }
            for row in rows
        ]
    })


@api_view(["GET", "POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def workspaces_view(request, tenant_id):
    tenant, actor_membership, error = _tenant_context(
        request, tenant_id, require_admin=request.method == "POST"
    )
    if error:
        return error

    if request.method == "GET":
        # Ensure legacy tenants created after the migration still acquire a
        # default workspace without creating a second tenant abstraction.
        get_default_workspace(tenant)
        rows = Workspace.objects.filter(tenant=tenant).order_by("-is_default", "name")
        if actor_membership.role not in ADMIN_ROLES:
            accessible_ids = set(
                WorkspaceMembership.objects.filter(
                    membership=actor_membership,
                    status=WorkspaceMembership.Status.ACTIVE,
                    workspace__status=Workspace.Status.ACTIVE,
                ).values_list("workspace_id", flat=True)
            )
            rows = rows.filter(pk__in=accessible_ids, status=Workspace.Status.ACTIVE)
        return Response({"workspaces": [_serialize_workspace(row, request.user) for row in rows]})

    data = request.data
    if not isinstance(data, dict) or set(data) - {"name", "description"}:
        return Response(
            {"detail": "Only name and description are accepted."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    name = data.get("name")
    description = data.get("description", "")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
        return Response({"detail": "Workspace name must contain 1–255 characters."}, status=400)
    if not isinstance(description, str) or len(description) > 4000:
        return Response({"detail": "Workspace description is invalid."}, status=400)

    try:
        with transaction.atomic():
            workspace = Workspace.objects.create(
                tenant=tenant,
                name=name.strip(),
                slug=_slug_for_workspace(tenant, name.strip()),
                description=description.strip(),
                created_by=request.user,
            )
            WorkspaceMembership.objects.update_or_create(
                workspace=workspace,
                membership=actor_membership,
                defaults={
                    "role": WorkspaceMembership.Role.ADMIN,
                    "status": WorkspaceMembership.Status.ACTIVE,
                    "created_by": request.user,
                },
            )
            _audit(
                request,
                tenant,
                ActivityLog.Action.CREATE_WORKSPACE,
                f"Created workspace: {workspace.name}",
                workspace_id=str(workspace.pk),
            )
    except IntegrityError:
        return Response({"detail": "A workspace with that identifier already exists."}, status=409)

    return Response({"workspace": _serialize_workspace(workspace, request.user)}, status=201)


@api_view(["PATCH"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def workspace_detail_view(request, tenant_id, workspace_id):
    tenant, workspace, error = _workspace_context(
        request, tenant_id, workspace_id, require_manager=True
    )
    if error:
        return error
    data = request.data
    if not isinstance(data, dict) or not data or set(data) - {"name", "description", "status"}:
        return Response(
            {"detail": "Supported fields are name, description, and status."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if "name" in data:
        name = data["name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
            return Response({"detail": "Workspace name must contain 1–255 characters."}, status=400)
        workspace.name = name.strip()
    if "description" in data:
        description = data["description"]
        if not isinstance(description, str) or len(description) > 4000:
            return Response({"detail": "Workspace description is invalid."}, status=400)
        workspace.description = description.strip()
    if "status" in data:
        if data["status"] not in Workspace.Status.values:
            return Response({"detail": "Invalid workspace status."}, status=400)
        if workspace.is_default and data["status"] != Workspace.Status.ACTIVE:
            return Response({"detail": "The default workspace cannot be archived."}, status=409)
        tenant_membership = active_membership(request.user, tenant.pk)
        if tenant_membership is None or tenant_membership.role not in ADMIN_ROLES:
            return Response({"detail": "Only organization administrators can archive a workspace."}, status=403)
        workspace.status = data["status"]

    try:
        workspace.save(update_fields=["name", "description", "status", "updated_at"])
    except IntegrityError:
        return Response({"detail": "Workspace update conflicts with an existing record."}, status=409)
    _audit(
        request,
        tenant,
        ActivityLog.Action.UPDATE_WORKSPACE,
        f"Updated workspace: {workspace.name}",
        workspace_id=str(workspace.pk),
        changed_fields=sorted(data.keys()),
    )
    return Response({"workspace": _serialize_workspace(workspace, request.user)})


@api_view(["GET", "POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def workspace_members_view(request, tenant_id, workspace_id):
    tenant, workspace, error = _workspace_context(
        request, tenant_id, workspace_id, require_manager=True
    )
    if error:
        return error

    if request.method == "GET":
        rows = WorkspaceMembership.objects.filter(workspace=workspace).select_related(
            "membership__user"
        ).order_by("membership__user__username")
        return Response({"members": [
            {
                "assignmentId": str(row.pk),
                "membershipId": str(row.membership_id),
                "userId": row.membership.user_id,
                "username": row.membership.user.get_username(),
                "email": row.membership.user.email,
                "organizationRole": row.membership.role,
                "workspaceRole": row.role,
                "status": row.status,
            }
            for row in rows
        ]})

    membership_id = request.data.get("membership_id") if isinstance(request.data, dict) else None
    role = request.data.get("role", WorkspaceMembership.Role.VIEWER) if isinstance(request.data, dict) else None
    if (
        not isinstance(request.data, dict)
        or "membership_id" not in request.data
        or set(request.data.keys()) - {"membership_id", "role"}
    ):
        return Response({"detail": "Only membership_id and role are accepted."}, status=400)
    if not _valid_uuid(membership_id):
        return Response({"detail": "membership_id must be a valid UUID."}, status=400)
    if role not in WORKSPACE_ROLES:
        return Response({"detail": "Invalid workspace role."}, status=400)
    if workspace.status != Workspace.Status.ACTIVE:
        return Response({"detail": "Archived workspaces cannot receive members."}, status=409)
    target = Membership.objects.filter(
        pk=membership_id,
        tenant=tenant,
        status=Membership.Status.ACTIVE,
        user__is_active=True,
    ).select_related("user").first()
    if target is None:
        return Response({"detail": "Active organization member not found."}, status=404)
    assignment, created = WorkspaceMembership.objects.update_or_create(
        workspace=workspace,
        membership=target,
        defaults={
            "role": role,
            "status": WorkspaceMembership.Status.ACTIVE,
            "created_by": request.user,
        },
    )
    if created or assignment.status == WorkspaceMembership.Status.ACTIVE:
        _audit(
            request,
            tenant,
            ActivityLog.Action.ADD_WORKSPACE_MEMBER,
            f"Assigned {target.user.get_username()} to workspace {workspace.name}",
            workspace_id=str(workspace.pk),
            membership_id=str(target.pk),
            role=role,
        )
    return Response({"member": {
        "assignmentId": str(assignment.pk),
        "membershipId": str(target.pk),
        "userId": target.user_id,
        "username": target.user.get_username(),
        "email": target.user.email,
        "organizationRole": target.role,
        "workspaceRole": assignment.role,
        "status": assignment.status,
    }}, status=201 if created else 200)


@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def workspace_member_detail_view(request, tenant_id, workspace_id, membership_id):
    tenant, workspace, error = _workspace_context(
        request, tenant_id, workspace_id, require_manager=True
    )
    if error:
        return error
    assignment = WorkspaceMembership.objects.filter(
        workspace=workspace,
        membership_id=membership_id,
        status=WorkspaceMembership.Status.ACTIVE,
    ).select_related("membership__user").first()
    if assignment is None:
        return Response({"detail": "Workspace membership not found."}, status=404)
    assignment.status = WorkspaceMembership.Status.REVOKED
    assignment.save(update_fields=["status", "updated_at"])
    _audit(
        request,
        tenant,
        ActivityLog.Action.REMOVE_WORKSPACE_MEMBER,
        f"Removed {assignment.membership.user.get_username()} from workspace {workspace.name}",
        workspace_id=str(workspace.pk),
        membership_id=str(assignment.membership_id),
    )
    return Response(status=status.HTTP_204_NO_CONTENT)



# Unified, workspace-ID-based member management for personal SaaS and business
# workspaces. Organization-specific routes above remain backward-compatible.
def _managed_workspace(request, workspace_id):
    workspace = Workspace.objects.select_related("tenant").filter(
        pk=workspace_id,
        tenant__status=Tenant.Status.ACTIVE,
        status=Workspace.Status.ACTIVE,
    ).first()
    if workspace is None or (workspace.is_default and workspace.tenant.kind == Tenant.Kind.PERSONAL):
        return None, Response({"detail": "Workspace is unavailable."}, status=404)
    if active_membership(request.user, workspace.tenant_id) is None or not can_access_workspace(request.user, workspace):
        return None, Response({"detail": "Workspace is unavailable."}, status=404)
    if not can_manage_workspace(request.user, workspace):
        return None, Response({"detail": "Workspace manager access is required."}, status=403)
    return workspace, None


def _serialize_managed_member(assignment, viewer):
    member = assignment.membership
    protected = member.role in ADMIN_ROLES
    return {
        "assignmentId": str(assignment.pk),
        "membershipId": str(member.pk),
        "userId": member.user_id,
        "username": member.user.get_username(),
        "email": member.user.email,
        "organizationRole": member.role,
        "workspaceRole": WorkspaceMembership.Role.ADMIN if protected else assignment.role,
        "status": assignment.status,
        "isSelf": member.user_id == viewer.pk,
        "isProtected": protected,
    }


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def my_workspace_members_view(request, workspace_id):
    workspace, error = _managed_workspace(request, workspace_id)
    if error is not None:
        return error
    try:
        page = int(request.query_params.get("page", "1"))
        size = int(request.query_params.get("page_size", "20"))
    except (TypeError, ValueError):
        return Response({"detail": "page and page_size must be positive integers."}, status=400)
    if page < 1 or not 1 <= size <= 50:
        return Response({"detail": "page must be positive and page_size must be 1–50."}, status=400)
    rows = WorkspaceMembership.objects.filter(
        workspace=workspace,
        status=WorkspaceMembership.Status.ACTIVE,
        membership__status=Membership.Status.ACTIVE,
        membership__user__is_active=True,
    ).select_related("membership__user").order_by("membership__user__username", "pk")
    total = rows.count()
    start = (page - 1) * size
    members = [_serialize_managed_member(row, request.user) for row in rows[start:start + size]]
    result = Response({
        "workspaceId": str(workspace.pk),
        "workspaceName": workspace.name,
        "members": members,
        "total": total,
        "page": page,
        "pageSize": size,
        "hasNext": start + size < total,
    })
    result["Cache-Control"] = "private, no-store"
    return result


def _can_remove_workspace_admin(workspace, assignment):
    """Require another effective manager if the assignment is the last admin."""
    if assignment.role != WorkspaceMembership.Role.ADMIN:
        return True
    active_tenant_managers = Membership.objects.filter(
        tenant=workspace.tenant,
        role__in=ADMIN_ROLES,
        status=Membership.Status.ACTIVE,
        user__is_active=True,
    ).exists()
    if active_tenant_managers:
        return True
    return WorkspaceMembership.objects.filter(
        workspace=workspace,
        role=WorkspaceMembership.Role.ADMIN,
        status=WorkspaceMembership.Status.ACTIVE,
        membership__status=Membership.Status.ACTIVE,
        membership__user__is_active=True,
    ).exclude(pk=assignment.pk).exists()


@api_view(["PATCH", "DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def my_workspace_member_detail_view(request, workspace_id, assignment_id):
    # Validate the payload before any mutation to avoid confusing partial writes.
    if request.method == "PATCH":
        data = request.data
        if not isinstance(data, dict) or set(data) != {"role"}:
            return Response({"detail": "Only role is accepted."}, status=400)
        role = data.get("role")
        if role not in WORKSPACE_ROLES:
            return Response({"detail": "Role must be admin, editor or viewer."}, status=400)
    else:
        role = None

    # All member mutations through this API serialize on the Workspace row,
    # keeping last-manager checks correct under concurrent requests.
    with transaction.atomic():
        workspace = Workspace.objects.select_for_update(of=("self",)).select_related("tenant").filter(
            pk=workspace_id,
            tenant__status=Tenant.Status.ACTIVE,
            status=Workspace.Status.ACTIVE,
        ).first()
        if workspace is None or (workspace.is_default and workspace.tenant.kind == Tenant.Kind.PERSONAL):
            return Response({"detail": "Workspace is unavailable."}, status=404)
        if active_membership(request.user, workspace.tenant_id) is None or not can_access_workspace(request.user, workspace):
            return Response({"detail": "Workspace is unavailable."}, status=404)
        if not can_manage_workspace(request.user, workspace):
            return Response({"detail": "Workspace manager access is required."}, status=403)
        assignment = WorkspaceMembership.objects.select_for_update(of=("self",)).select_related(
            "membership", "membership__user"
        ).filter(
            pk=assignment_id,
            workspace=workspace,
            status=WorkspaceMembership.Status.ACTIVE,
            membership__status=Membership.Status.ACTIVE,
            membership__user__is_active=True,
        ).first()
        if assignment is None:
            return Response({"detail": "Active workspace member not found."}, status=404)
        if assignment.membership.user_id == request.user.pk:
            return Response({"detail": "You cannot change or revoke your own workspace access."}, status=409)
        if assignment.membership.role in ADMIN_ROLES:
            return Response({"detail": "Organization owners and administrators must be managed at organization level."}, status=403)
        if request.method == "PATCH":
            if role == assignment.role:
                return Response({"member": _serialize_managed_member(assignment, request.user), "changed": False})
            if not _can_remove_workspace_admin(workspace, assignment):
                return Response({"detail": "The workspace must retain at least one manager."}, status=409)
            old_role = assignment.role
            assignment.role = role
            assignment.save(update_fields=["role", "updated_at"])
            _audit(
                request, workspace.tenant, ActivityLog.Action.ADD_WORKSPACE_MEMBER,
                f"Changed {assignment.membership.user.get_username()} from {old_role} to {role} in {workspace.name}",
                workspace_id=str(workspace.pk), membership_id=str(assignment.membership_id),
                operation="role_changed", previous_role=old_role, role=role,
            )
            return Response({"member": _serialize_managed_member(assignment, request.user), "changed": True})

        if not _can_remove_workspace_admin(workspace, assignment):
            return Response({"detail": "The workspace must retain at least one manager."}, status=409)
        assignment.status = WorkspaceMembership.Status.REVOKED
        assignment.save(update_fields=["status", "updated_at"])
        _audit(
            request, workspace.tenant, ActivityLog.Action.REMOVE_WORKSPACE_MEMBER,
            f"Removed {assignment.membership.user.get_username()} from workspace {workspace.name}",
            workspace_id=str(workspace.pk), membership_id=str(assignment.membership_id),
            operation="revoked", previous_role=assignment.role,
        )
    return Response(status=204)


# Personal SaaS workspace lifecycle. These routes use a workspace UUID as the
# selector and then re-check the caller's tenant membership and workspace role.
@api_view(["GET", "POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def my_workspaces_view(request):
    if request.method == "GET":
        rows = Workspace.objects.filter(
            tenant__memberships__user=request.user,
            tenant__memberships__status=Membership.Status.ACTIVE,
            tenant__status=Tenant.Status.ACTIVE,
            status=Workspace.Status.ACTIVE,
        ).select_related("tenant", "tenant__personal_owner", "created_by").distinct()
        workspaces = []
        for workspace in rows:
            # A personal tenant's default workspace is My Drive, not a shared
            # workspace in the switcher. Business default workspaces remain visible.
            if workspace.tenant.kind == Tenant.Kind.PERSONAL and workspace.is_default:
                continue
            if not can_access_workspace(request.user, workspace):
                continue
            workspaces.append(_serialize_workspace(workspace, request.user))
        workspaces.sort(key=lambda item: (not item["isOwnedByMe"], item["name"].casefold(), item["id"]))
        return Response({"workspaces": workspaces})

    data = request.data
    allowed = {"name", "description", "default_member_role"}
    if not isinstance(data, dict) or set(data) - allowed:
        return Response({"detail": "Only name, description and default_member_role are accepted."}, status=400)
    name = data.get("name")
    description = data.get("description", "")
    default_member_role = data.get("default_member_role", "viewer")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
        return Response({"detail": "Workspace name must contain 1–255 characters."}, status=400)
    if not isinstance(description, str) or len(description) > 4000:
        return Response({"detail": "Workspace description is invalid."}, status=400)
    if default_member_role not in {WorkspaceMembership.Role.VIEWER, WorkspaceMembership.Role.EDITOR}:
        return Response({"detail": "Default member role must be viewer or editor."}, status=400)

    try:
        tenant = get_personal_tenant(request.user)
        owner_membership = active_membership(request.user, tenant.pk)
        if owner_membership is None or tenant.personal_owner_id != request.user.pk:
            return Response({"detail": "Only the personal drive owner can create a workspace here."}, status=403)
        with transaction.atomic():
            workspace = Workspace.objects.create(
                tenant=tenant,
                name=name.strip(),
                slug=_slug_for_workspace(tenant, name.strip()),
                description=description.strip(),
                default_member_role=default_member_role,
                created_by=request.user,
            )
            WorkspaceMembership.objects.update_or_create(
                workspace=workspace,
                membership=owner_membership,
                defaults={
                    "role": WorkspaceMembership.Role.ADMIN,
                    "status": WorkspaceMembership.Status.ACTIVE,
                    "created_by": request.user,
                },
            )
            _audit(
                request,
                tenant,
                ActivityLog.Action.CREATE_WORKSPACE,
                f"Created workspace: {workspace.name}",
                workspace_id=str(workspace.pk),
                default_member_role=default_member_role,
            )
    except IntegrityError:
        return Response({"detail": "A workspace with that identifier already exists."}, status=409)
    return Response({"workspace": _serialize_workspace(workspace, request.user)}, status=201)


@api_view(["PATCH"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def my_workspace_detail_view(request, workspace_id):
    workspace = Workspace.objects.select_related("tenant", "tenant__personal_owner", "created_by").filter(
        pk=workspace_id,
        tenant__status=Tenant.Status.ACTIVE,
    ).first()
    if workspace is None:
        return Response({"detail": "Workspace is unavailable."}, status=404)
    if not can_manage_workspace(request.user, workspace):
        return Response({"detail": "Workspace administrator access is required."}, status=403)

    data = request.data
    allowed = {"name", "description", "status", "default_member_role"}
    if not isinstance(data, dict) or not data or set(data) - allowed:
        return Response({"detail": "Supported fields are name, description, status and default_member_role."}, status=400)
    changed_fields = sorted(data.keys())
    if "name" in data:
        name = data["name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
            return Response({"detail": "Workspace name must contain 1–255 characters."}, status=400)
        workspace.name = name.strip()
    if "description" in data:
        description = data["description"]
        if not isinstance(description, str) or len(description) > 4000:
            return Response({"detail": "Workspace description is invalid."}, status=400)
        workspace.description = description.strip()
    if "default_member_role" in data:
        if data["default_member_role"] not in {WorkspaceMembership.Role.VIEWER, WorkspaceMembership.Role.EDITOR}:
            return Response({"detail": "Default member role must be viewer or editor."}, status=400)
        workspace.default_member_role = data["default_member_role"]
    if "status" in data:
        if data["status"] not in Workspace.Status.values:
            return Response({"detail": "Invalid workspace status."}, status=400)
        if workspace.is_default and data["status"] != Workspace.Status.ACTIVE:
            return Response({"detail": "The default My Drive workspace cannot be archived."}, status=409)
        # Archiving is available to workspace managers; it does not delete content.
        workspace.status = data["status"]
    try:
        workspace.save(update_fields=[*changed_fields, "updated_at"])
    except IntegrityError:
        return Response({"detail": "Workspace update conflicts with an existing record."}, status=409)
    _audit(
        request,
        workspace.tenant,
        ActivityLog.Action.UPDATE_WORKSPACE,
        f"Updated workspace: {workspace.name}",
        workspace_id=str(workspace.pk),
        changed_fields=changed_fields,
    )
    return Response({"workspace": _serialize_workspace(workspace, request.user)})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_workspace_invite_view(request, workspace_id):
    workspace = Workspace.objects.select_related("tenant", "tenant__personal_owner").filter(
        pk=workspace_id,
        tenant__status=Tenant.Status.ACTIVE,
        status=Workspace.Status.ACTIVE,
    ).first()
    if workspace is None:
        return Response({"detail": "Workspace is unavailable."}, status=404)
    if not can_manage_workspace(request.user, workspace):
        return Response({"detail": "Only workspace managers can invite members."}, status=403)

    data = request.data
    if not isinstance(data, dict) or set(data) - {"email", "role"} or "email" not in data:
        return Response({"detail": "Only email and role are accepted."}, status=400)
    email = data.get("email")
    role = data.get("role", workspace.default_member_role)
    if not isinstance(email, str):
        return Response({"detail": "Enter a valid email address."}, status=400)
    email = email.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        return Response({"detail": "Enter a valid email address."}, status=400)
    if role not in {WorkspaceMembership.Role.VIEWER, WorkspaceMembership.Role.EDITOR}:
        return Response({"detail": "Invite role must be viewer or editor."}, status=400)

    already_member = Membership.objects.filter(
        tenant=workspace.tenant,
        user__email__iexact=email,
        status=Membership.Status.ACTIVE,
        workspace_assignments__workspace=workspace,
        workspace_assignments__status=WorkspaceMembership.Status.ACTIVE,
    ).exists()
    if already_member:
        return Response({"detail": "This user is already a member of the workspace."}, status=409)

    now = timezone.now()
    WorkspaceInvite.objects.filter(
        workspace=workspace,
        email__iexact=email,
        accepted_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=now)

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    invitation = WorkspaceInvite.objects.create(
        workspace=workspace,
        email=email,
        token_hash=token_hash,
        role=role,
        invited_by=request.user,
        expires_at=now + timedelta(days=7),
    )
    _audit(
        request,
        workspace.tenant,
        ActivityLog.Action.INVITE_WORKSPACE_MEMBER,
        f"Invited {email} to workspace {workspace.name}",
        workspace_id=str(workspace.pk),
        invitation_id=str(invitation.pk),
        invited_email=email,
        role=role,
        expires_at=invitation.expires_at.isoformat(),
    )
    # The raw token is returned once for a copyable invitation URL; only its hash is stored.
    return Response({
        "invitationId": str(invitation.pk),
        "email": email,
        "role": role,
        "workspaceId": str(workspace.pk),
        "workspaceName": workspace.name,
        "inviteToken": raw_token,
        "expiresAt": invitation.expires_at,
    }, status=201)


def _workspace_invite_for_token(raw_token):
    if not isinstance(raw_token, str) or not raw_token.strip() or len(raw_token) > 256:
        return None
    token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
    return WorkspaceInvite.objects.select_related(
        "workspace", "workspace__tenant", "workspace__created_by", "invited_by"
    ).filter(token_hash=token_hash).first()


def _invite_is_usable(invitation):
    return bool(
        invitation
        and invitation.revoked_at is None
        and invitation.accepted_at is None
        and invitation.expires_at > timezone.now()
        and invitation.workspace.status == Workspace.Status.ACTIVE
        and invitation.workspace.tenant.status == Tenant.Status.ACTIVE
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def preview_workspace_invite_view(request):
    invitation = _workspace_invite_for_token(request.query_params.get("token"))
    if invitation is None:
        return Response({"detail": "Invitation not found."}, status=404)
    if not _invite_is_usable(invitation):
        return Response({"detail": "This invitation has expired, been revoked, or was already used."}, status=410)
    if not request.user.email or request.user.email.strip().lower() != invitation.email.lower():
        return Response({"detail": "Sign in with the email address this invitation was sent to."}, status=403)
    creator = invitation.invited_by.get_username() if invitation.invited_by_id else "A workspace manager"
    return Response({
        "workspaceId": str(invitation.workspace_id),
        "workspaceName": invitation.workspace.name,
        "workspaceDescription": invitation.workspace.description,
        "invitedEmail": invitation.email,
        "role": invitation.role,
        "invitedBy": creator,
        "expiresAt": invitation.expires_at,
    })


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def accept_workspace_invite_view(request):
    data = request.data
    if not isinstance(data, dict) or set(data) != {"token"}:
        return Response({"detail": "A single invitation token is required."}, status=400)
    raw_token = data.get("token")
    if not isinstance(raw_token, str):
        return Response({"detail": "Invalid invitation token."}, status=400)
    token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
    with transaction.atomic():
        invitation = WorkspaceInvite.objects.select_for_update().select_related(
            "workspace", "workspace__tenant"
        ).filter(token_hash=token_hash).first()
        if invitation is None:
            return Response({"detail": "Invitation not found."}, status=404)
        if not _invite_is_usable(invitation):
            return Response({"detail": "This invitation has expired, been revoked, or was already used."}, status=410)
        if not request.user.email or request.user.email.strip().lower() != invitation.email.lower():
            return Response({"detail": "This invitation belongs to a different email address."}, status=403)
        if not request.user.is_active:
            return Response({"detail": "Inactive accounts cannot join workspaces."}, status=403)

        membership = Membership.objects.select_for_update().filter(
            tenant=invitation.workspace.tenant,
            user=request.user,
        ).first()
        if membership is None:
            membership = Membership.objects.create(
                tenant=invitation.workspace.tenant,
                user=request.user,
                role=Membership.Role.MEMBER,
                status=Membership.Status.ACTIVE,
            )
        elif membership.status == Membership.Status.SUSPENDED:
            return Response({"detail": "Your membership in this organization is suspended."}, status=403)
        elif membership.status in {Membership.Status.REVOKED, Membership.Status.INVITED}:
            membership.status = Membership.Status.ACTIVE
            if membership.role not in {Membership.Role.OWNER, Membership.Role.ADMIN}:
                membership.role = Membership.Role.MEMBER
            membership.save(update_fields=["status", "role", "updated_at"])

        assignment = WorkspaceMembership.objects.filter(
            workspace=invitation.workspace,
            membership=membership,
        ).first()
        already_member = bool(assignment and assignment.status == WorkspaceMembership.Status.ACTIVE)
        if not already_member:
            WorkspaceMembership.objects.update_or_create(
                workspace=invitation.workspace,
                membership=membership,
                defaults={
                    "role": invitation.role,
                    "status": WorkspaceMembership.Status.ACTIVE,
                    "created_by": invitation.invited_by,
                },
            )
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at"])
        _audit(
            request,
            invitation.workspace.tenant,
            ActivityLog.Action.JOIN_WORKSPACE,
            f"Joined workspace {invitation.workspace.name}",
            workspace_id=str(invitation.workspace_id),
            invitation_id=str(invitation.pk),
            role=invitation.role,
        )
    return Response({
        "joined": True,
        "alreadyMember": already_member,
        "workspace": _serialize_workspace(invitation.workspace, request.user),
    }, status=200)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def workspace_activity_view(request, workspace_id):
    workspace = Workspace.objects.select_related("tenant").filter(
        pk=workspace_id,
        tenant__status=Tenant.Status.ACTIVE,
        status=Workspace.Status.ACTIVE,
    ).first()
    if workspace is None:
        return Response({"detail": "Workspace is unavailable."}, status=404)
    if not can_manage_workspace(request.user, workspace):
        return Response({"detail": "Workspace administrator access is required to view its timeline."}, status=403)
    try:
        limit = int(request.query_params.get("limit", "100"))
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 200))
    rows = ActivityLog.objects.filter(workspace=workspace).exclude(
        action=ActivityLog.Action.SEARCH,
    ).select_related("user").order_by("-created_at")[:limit]
    return Response({"events": [
        {
            "id": row.pk,
            "username": row.user.get_username(),
            "action": row.action,
            "actionLabel": row.get_action_display(),
            "description": row.description,
            "createdAt": row.created_at,
            "metadata": row.metadata,
        }
        for row in rows
    ]})