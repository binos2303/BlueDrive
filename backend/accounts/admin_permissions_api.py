"""Live, read-only role directory for the Admin Console.

This reports real auth roles and persisted assignments; it does not create a
second authorization source or offer fabricated role-transfer operations.
"""

from django.contrib.auth import get_user_model
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from .admin_api import IsPlatformAdmin
from .models import Membership, PlatformAdminIdentity, Tenant, Workspace, WorkspaceMembership


# UI descriptions of EXISTING policies, not policy evaluation logic.
# All authorization continues to live in platform_admin.py, access.py and
# sharing/services.py. These rows must never be used to grant capabilities.
ROLE_REFERENCE = (
    {
        "id": "super_admin", "scope": "platform", "label": "Super Admin",
        "description": "Django staff superuser: platform administration and file recovery operations.",
        "capabilities": ["Manage platform administrators", "Suspend/reactivate user accounts", "Manage file Trash/restore/purge with audit"],
        "restriction": "Platform status alone never grants access to file contents.",
    },
    {
        "id": "platform_admin", "scope": "platform", "label": "Platform Admin",
        "description": "Active, dedicated platform administrator with staff status.",
        "capabilities": ["View system metadata and audit", "Suspend/reactivate ordinary user accounts", "Revoke ordinary user sessions"],
        "restriction": "Cannot administer other platform admins, purge user files or read file contents.",
    },
    {
        "id": "tenant_owner", "scope": "tenant", "label": "Tenant Owner",
        "description": "Active owner membership in a personal or business tenant.",
        "capabilities": ["Manage active workspaces in the tenant", "Administer tenant workspace membership", "Read/edit content within active tenant workspaces"],
        "restriction": "Not a platform administrator; access is limited to their tenant.",
    },
    {
        "id": "tenant_admin", "scope": "tenant", "label": "Tenant Admin",
        "description": "Organization-scoped administrator membership.",
        "capabilities": ["Manage active tenant workspaces", "Administer workspace members", "Read/edit active tenant workspace content"],
        "restriction": "Not a platform administrator and cannot access other tenants.",
    },
    {
        "id": "tenant_member", "scope": "tenant", "label": "Tenant Member",
        "description": "Active tenant membership without tenant-wide administrative rights.",
        "capabilities": ["Access assigned active workspaces", "Use separately granted direct shares"],
        "restriction": "Tenant membership alone does not grant access to every workspace.",
    },
    {
        "id": "workspace_admin", "scope": "workspace", "label": "Workspace Admin",
        "description": "Admin assignment within an active, non-default workspace.",
        "capabilities": ["View and edit workspace content", "Manage workspace members and invitations"],
        "restriction": "Cannot manage platform accounts or unrelated tenants/workspaces.",
    },
    {
        "id": "workspace_editor", "scope": "workspace", "label": "Workspace Editor",
        "description": "Editor assignment within an active, non-default workspace.",
        "capabilities": ["View and download workspace content", "Create, rename and edit permitted workspace items"],
        "restriction": "Cannot manage workspace membership or other owners' direct shares.",
    },
    {
        "id": "workspace_viewer", "scope": "workspace", "label": "Workspace Viewer",
        "description": "Read-only assignment within an active, non-default workspace.",
        "capabilities": ["View and download accessible workspace content"],
        "restriction": "Cannot edit content or administer workspace members.",
    },
)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_permissions_view(request):
    """Current role/assignment counts from PostgreSQL, never hard-coded demo users."""
    user_model = get_user_model()
    platform_counts = {
        "super_admin": user_model.objects.filter(is_active=True, is_staff=True, is_superuser=True).count(),
        "platform_admin": PlatformAdminIdentity.objects.filter(
            status=PlatformAdminIdentity.Status.ACTIVE,
            user__is_active=True, user__is_staff=True, user__is_superuser=False,
        ).count(),
    }
    tenant_assignments = Membership.objects.filter(
        status=Membership.Status.ACTIVE,
        tenant__status=Tenant.Status.ACTIVE, user__is_active=True,
    )
    workspace_assignments = WorkspaceMembership.objects.filter(
        status=WorkspaceMembership.Status.ACTIVE,
        workspace__status=Workspace.Status.ACTIVE, workspace__is_default=False,
        workspace__tenant__status=Tenant.Status.ACTIVE,
        membership__status=Membership.Status.ACTIVE,
        membership__user__is_active=True,
    )
    counts = {
        **platform_counts,
        "tenant_owner": tenant_assignments.filter(role=Membership.Role.OWNER).count(),
        "tenant_admin": tenant_assignments.filter(role=Membership.Role.ADMIN).count(),
        "tenant_member": tenant_assignments.filter(role=Membership.Role.MEMBER).count(),
        "workspace_admin": workspace_assignments.filter(role=WorkspaceMembership.Role.ADMIN).count(),
        "workspace_editor": workspace_assignments.filter(role=WorkspaceMembership.Role.EDITOR).count(),
        "workspace_viewer": workspace_assignments.filter(role=WorkspaceMembership.Role.VIEWER).count(),
    }
    rows = [
        {
            **reference,
            "count": counts[reference["id"]],
            "count_unit": "accounts" if reference["scope"] == "platform" else "assignments",
        }
        for reference in ROLE_REFERENCE
    ]
    response = Response({
        "roles": rows,
        "notes": [
            "Counts are active accounts or role assignments, not unique people; one person may hold multiple scoped roles.",
            "Workspace counts exclude private/default workspaces and do not include Tenant Owners/Admins who inherit workspace management rights.",
            "Direct file/folder shares grant separate per-resource Viewer/Editor access; they are not tenant or workspace roles.",
            "This page is read-only. Actual authorization is enforced on each Django API request.",
        ],
    })
    response["Cache-Control"] = "private, no-store"
    return response
