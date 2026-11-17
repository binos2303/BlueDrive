"""JSON management of *direct* file/folder grants for the Next.js Drive.

Workspace membership and inherited folder access are intentionally separate:
revoking a direct grant does not revoke a user's Workspace membership.
"""
import json

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from accounts.access import (
    active_tenant_required as login_required,
    can_access_workspace,
    get_default_tenant,
    resolve_request_workspace,
)
from files.models import File
from folders.models import Folder
from .models import Share
from .services import (
    can_manage_direct_share,
    can_view_file,
    can_view_folder,
    change_direct_share_permission,
    revoke_direct_share,
)


def _context(request):
    workspace = resolve_request_workspace(request)
    if workspace is None or not can_access_workspace(request.user, workspace):
        return None
    return workspace


def _error(detail, status):
    response = JsonResponse({"detail": detail}, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _parse_positive_id(raw):
    # Reject bool-like and signed identifiers; do not allow unchecked coercion.
    if not isinstance(raw, str) or len(raw) > 19 or not raw.isdecimal():
        return None
    number = int(raw)
    return number if 0 < number <= 2**63 - 1 else None


def _resource(workspace, user, kind, resource_id):
    model = File if kind == "file" else Folder
    obj = model.objects.filter(
        pk=resource_id,
        owner=user,
        tenant=workspace.tenant,
        workspace=workspace,
        deleted_at__isnull=True,
    ).select_related("tenant", "workspace", "folder" if kind == "file" else "parent").first()
    if obj is None:
        return None
    if not (can_view_file(obj, user) if kind == "file" else can_view_folder(obj, user)):
        return None
    return obj


def _serialized_share(share):
    kind = "file" if share.file_id else "folder"
    resource = share.file if share.file_id else share.folder
    return {
        "id": share.pk,
        "item": {"kind": kind, "id": resource.pk, "name": resource.file_name if kind == "file" else resource.folder_name},
        "recipient": {"username": share.receiver.get_username(), "email": share.receiver.email},
        "permission": share.permission,
        "created_at": share.created_at.isoformat(),
    }


@login_required
@require_GET
def direct_shares_view(request):
    """List grants owned by this user in the active Workspace, or one item."""
    workspace = _context(request)
    if workspace is None:
        return _error("Workspace is unavailable.", 404)

    kind = request.GET.get("kind")
    raw_id = request.GET.get("id")
    if (kind is None) != (raw_id is None):
        return _error("Provide both kind and id, or neither.", 400)
    if kind is not None:
        resource_id = _parse_positive_id(raw_id)
        if kind not in {"file", "folder"} or resource_id is None:
            return _error("Invalid item kind or ID.", 400)
        resource = _resource(workspace, request.user, kind, resource_id)
        if resource is None:
            return _error("Item not found.", 404)
    else:
        resource = None

    page_raw = request.GET.get("page", "1")
    size_raw = request.GET.get("page_size", "20")
    page = _parse_positive_id(page_raw)
    page_size = _parse_positive_id(size_raw)
    if page is None or page_size is None or page_size > 50:
        return _error("Invalid pagination parameters (page_size must be 1–50).", 400)

    grants = Share.objects.filter(
        owner=request.user,
        tenant=workspace.tenant,
    ).filter(
        Q(file__workspace=workspace, file__tenant=workspace.tenant, file__owner=request.user, file__deleted_at__isnull=True)
        | Q(folder__workspace=workspace, folder__tenant=workspace.tenant, folder__owner=request.user, folder__deleted_at__isnull=True)
    ).select_related("file", "folder", "receiver").order_by("-created_at", "-pk")
    if resource is not None:
        grants = grants.filter(**({"file": resource} if kind == "file" else {"folder": resource}))
    # For an overview, avoid grants whose parent is directly in Trash. Deeper
    # ancestry is protected by the resource permission checks on mutations.
    else:
        grants = grants.filter(
            Q(file__isnull=False, file__folder__deleted_at__isnull=True)
            | Q(folder__isnull=False, folder__parent__deleted_at__isnull=True)
        )

    paginator = Paginator(grants, page_size)
    if page > max(paginator.num_pages, 1):
        return _error("Page not found.", 404)
    current = paginator.page(page)
    response = JsonResponse({
        "items": [_serialized_share(grant) for grant in current.object_list],
        "page": page,
        "page_size": page_size,
        "total": paginator.count,
        "pages": paginator.num_pages,
        "item": ({"kind": kind, "id": resource.pk, "name": resource.file_name if kind == "file" else resource.folder_name}
                 if resource is not None else None),
        "can_manage": can_manage_direct_share(resource, request.user) if resource is not None else None,
    })
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_http_methods(["PATCH", "DELETE"])
def direct_share_detail_view(request, share_id):
    """Update or revoke a grant using row-level locking and atomic auditing."""
    workspace = _context(request)
    if workspace is None:
        return _error("Workspace is unavailable.", 404)

    if request.method == "PATCH":
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _error("Invalid JSON request body.", 400)
        if not isinstance(payload, dict) or set(payload) != {"permission"}:
            return _error("Provide only the permission field.", 400)
        permission = payload.get("permission")
        if permission not in (Share.Permission.VIEWER, Share.Permission.EDITOR):
            return _error("Permission must be viewer or editor.", 400)

    with transaction.atomic():
        share = Share.objects.select_for_update(of=("self",)).filter(
            pk=share_id, owner=request.user, tenant=workspace.tenant,
        ).filter(
            Q(file__workspace=workspace, file__tenant=workspace.tenant, file__owner=request.user)
            | Q(folder__workspace=workspace, folder__tenant=workspace.tenant, folder__owner=request.user)
        ).select_related("file__tenant", "file__workspace", "file__folder", "folder__tenant", "folder__workspace", "folder__parent", "receiver").first()
        if share is None:
            return _error("Share not found.", 404)
        resource = share.file if share.file_id else share.folder
        if resource.deleted_at is not None:
            return _error("Share not found.", 404)
        if not can_manage_direct_share(resource, request.user):
            return _error("You cannot manage sharing for this item.", 403)
        if request.method == "PATCH":
            changed = change_direct_share_permission(share=share, actor=request.user, permission=permission)
            response = JsonResponse({"changed": changed, "share": _serialized_share(share),
                                     "detail": "Permission updated." if changed else "Permission is unchanged."})
        else:
            revoke_direct_share(share=share, actor=request.user)
            response = JsonResponse({"detail": "Access revoked.", "revoked": True})
        response["Cache-Control"] = "private, no-store"
        return response
