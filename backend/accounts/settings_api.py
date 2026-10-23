"""Self-service APIs for personal activity, quota, privacy, and data deletion."""
from django.contrib.auth.hashers import check_password
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.access import get_default_tenant, get_default_workspace, resolve_request_workspace
from accounts.models import QuotaAccount, Tenant
from accounts.services import get_personal_tenant
from files.models import File
from files.permanent_delete import PermanentDeleteError, permanently_delete_files
from folders.models import Folder
from logs.models import ActivityLog, SearchHistory


def _selected_workspace(request):
    try:
        tenant = get_default_tenant(request.user)
        workspace = resolve_request_workspace(request, tenant)
    except Exception:
        return None, None
    if workspace is None:
        return None, None
    return workspace.tenant, workspace


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def my_quota_view(request):
    tenant, workspace = _selected_workspace(request)
    if tenant is None or workspace is None:
        return Response({"detail": "An accessible workspace is required."}, status=404)

    # Personal-tenant owners see their own tenant quota. Guests do not see the
    # owner's aggregate usage because that includes private My Drive data. For
    # business tenants, upload enforcement requires both tenant and member caps.
    member_quota = QuotaAccount.objects.filter(
        tenant=tenant,
        scope=QuotaAccount.Scope.MEMBER,
        user=request.user,
    ).first()
    is_personal_owner = (
        tenant.kind == Tenant.Kind.PERSONAL
        and tenant.personal_owner_id == request.user.pk
    )
    tenant_quota = QuotaAccount.objects.filter(
        tenant=tenant,
        scope=QuotaAccount.Scope.TENANT,
    ).first()

    context = {
        "workspaceId": str(workspace.pk),
        "tenantName": tenant.name,
    }

    if tenant.kind == Tenant.Kind.PERSONAL and not is_personal_owner:
        # Uploads in a shared personal workspace consume the owner's tenant
        # quota. That aggregate includes the owner's private My Drive, so it is
        # intentionally not exposed to collaborators; individual usage is not
        # yet tracked for personal-tenant guests.
        message = (
            "Shared workspace storage is charged to the owner's plan. "
            "Individual usage is not currently tracked or displayed."
        )
        if tenant_quota is None:
            message = (
                "The workspace owner has not configured shared storage quota. "
                "Uploads may be unavailable until the owner configures storage."
            )
        return Response({
            **context,
            "configured": False,
            "limitBytes": None,
            "usedBytes": None,
            "reservedBytes": None,
            "remainingBytes": None,
            "percentUsed": None,
            "message": message,
        })

    if tenant.kind == Tenant.Kind.BUSINESS:
        if tenant_quota is None:
            return Response({
                **context,
                "configured": False,
                "limitBytes": None,
                "usedBytes": None,
                "reservedBytes": None,
                "remainingBytes": None,
                "percentUsed": None,
                "message": "Organization storage quota is not configured; uploads are unavailable until an administrator configures it.",
            })
        if member_quota is None:
            return Response({
                **context,
                "configured": False,
                "limitBytes": None,
                "usedBytes": None,
                "reservedBytes": None,
                "remainingBytes": None,
                "percentUsed": None,
                "message": "An administrator must allocate a member quota before you can upload to this organization workspace.",
            })
        quota = member_quota
    else:
        quota = tenant_quota

    if quota is None:
        return Response({
            **context,
            "configured": False,
            "limitBytes": None,
            "usedBytes": 0,
            "reservedBytes": 0,
            "remainingBytes": None,
            "percentUsed": None,
            "message": "Storage quota is not configured.",
        })

    def summary(account):
        limit_bytes = account.limit_bytes
        used_bytes = max(0, int(account.used_bytes))
        reserved_bytes = max(0, int(account.reserved_bytes))
        remaining = None if limit_bytes is None else max(0, int(limit_bytes) - used_bytes - reserved_bytes)
        percent = None if not limit_bytes else min(100, round((used_bytes + reserved_bytes) * 100 / limit_bytes))
        return {
            "limitBytes": limit_bytes,
            "usedBytes": used_bytes,
            "reservedBytes": reserved_bytes,
            "remainingBytes": remaining,
            "percentUsed": percent,
        }

    result = {
        **context,
        "configured": True,
        "scope": quota.scope,
        **summary(quota),
        "updatedAt": quota.updated_at,
    }
    # Business uploads reserve against both the member allocation and the
    # organization cap. Surface both so the sidebar does not imply that a
    # member can use more than the organization's remaining capacity.
    if tenant.kind == Tenant.Kind.BUSINESS and tenant_quota is not None:
        result["organizationCap"] = summary(tenant_quota)
    return Response(result)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def my_activity_view(request):
    try:
        limit = int(request.query_params.get("limit", "50"))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 100))
    rows = ActivityLog.objects.filter(user=request.user).select_related(
        "tenant", "workspace"
    ).order_by("-created_at")[:limit]
    return Response({"events": [
        {
            "id": row.pk,
            "action": row.action,
            "actionLabel": row.get_action_display(),
            "description": row.description,
            "tenantName": row.tenant.name if row.tenant_id else None,
            "workspaceId": str(row.workspace_id) if row.workspace_id else None,
            "workspaceName": row.workspace.name if row.workspace_id else None,
            "createdAt": row.created_at,
            "metadata": row.metadata if isinstance(row.metadata, dict) else {},
        }
        for row in rows
    ]})


@api_view(["GET", "DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def my_search_history_view(request):
    history = SearchHistory.objects.filter(user=request.user)
    if request.method == "DELETE":
        deleted_count, _ = history.delete()
        return Response({"deletedCount": deleted_count})

    try:
        limit = int(request.query_params.get("limit", "50"))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 100))
    rows = history.select_related("workspace").order_by("-created_at")[:limit]
    return Response({"items": [
        {
            "id": row.pk,
            "query": row.query,
            "resultCount": row.result_count,
            "workspaceName": row.workspace.name if row.workspace_id else None,
            "createdAt": row.created_at,
        }
        for row in rows
    ]})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_my_drive_data_view(request):
    if not isinstance(request.data, dict) or set(request.data) != {"confirmation", "password"}:
        return Response({"detail": "Confirmation and current password are required."}, status=400)
    if request.data.get("confirmation") != "DELETE MY DRIVE":
        return Response({"detail": "Type DELETE MY DRIVE exactly to confirm."}, status=400)
    password = request.data.get("password")
    if not isinstance(password, str) or not password or not check_password(password, request.user.password):
        return Response({"detail": "The current password is incorrect."}, status=403)

    # This action is intentionally restricted to the user's private default
    # workspace. It does not delete shared workspace content, the account, or
    # the retained security audit log.
    personal_tenant = get_personal_tenant(request.user)
    workspace = get_default_workspace(personal_tenant)
    drive_files = list(File.objects.filter(
        tenant=personal_tenant,
        workspace=workspace,
        owner=request.user,
    ))
    folder_count = Folder.objects.filter(
        tenant=personal_tenant,
        workspace=workspace,
        owner=request.user,
    ).count()

    try:
        deleted_files = permanently_delete_files(drive_files)
    except PermanentDeleteError:
        # Keep adapter/object references and lower-level storage details in the
        # server logs, not in a self-service response returned to the client.
        return Response({
            "detail": "Some storage objects could not be deleted. The request was stopped so it can be retried safely.",
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    Folder.objects.filter(
        tenant=personal_tenant,
        workspace=workspace,
        owner=request.user,
    ).delete()

    ActivityLog.objects.create(
        user=request.user,
        tenant=personal_tenant,
        workspace=workspace,
        action=ActivityLog.Action.DELETE_MY_DRIVE_DATA,
        description="Permanently deleted all files and folders in My Drive.",
        metadata={"filesDeleted": deleted_files, "foldersDeleted": folder_count},
    )
    return Response({
        "detail": "My Drive data was permanently deleted.",
        "filesDeleted": deleted_files,
        "foldersDeleted": folder_count,
        "auditLogRetained": True,
    })
