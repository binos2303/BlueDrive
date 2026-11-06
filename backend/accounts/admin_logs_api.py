"""Read-only platform log directories.

User activity comes from the existing logs.ActivityLog table. Administrative
changes come from accounts.PlatformAdminAuditEvent. These streams remain
separate and expose only the metadata needed by an operational log viewer.

Never send raw ActivityLog.description, .metadata, .request_id, search queries,
object storage identifiers, session keys or arbitrary admin audit metadata.
"""

from datetime import date, datetime, time
import re

from django.db.models import Q
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from logs.models import ActivityLog
from .admin_api import IsPlatformAdmin
from .models import PlatformAdminAuditEvent, Tenant


PAGE_SIZE = 20
MAX_SEARCH_LENGTH = 100
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _page_number(request):
    raw = request.query_params.get("page", "1")
    try:
        page = int(raw)
    except (TypeError, ValueError):
        return None
    return page if 1 <= page <= 100_000 else None


def _date_filters(request):
    """Return database-safe inclusive bounds, or a validation error response."""
    bounds = []
    for name in ("from", "to"):
        raw = request.query_params.get(name, "")
        if not raw:
            bounds.append(None)
            continue
        if not isinstance(raw, str) or not _DATE_PATTERN.fullmatch(raw):
            return None, Response({"detail": f"Invalid '{name}' date (use YYYY-MM-DD)."}, status=400)
        try:
            bounds.append(date.fromisoformat(raw))
        except ValueError:
            return None, Response({"detail": f"Invalid '{name}' date (use YYYY-MM-DD)."}, status=400)
    start, end = bounds
    if start and end and start > end:
        return None, Response({"detail": "'from' must be on or before 'to'."}, status=400)
    zone = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(start, time.min), zone) if start else None,
        timezone.make_aware(datetime.combine(end, time.max), zone) if end else None,
    ), None


def _apply_range(queryset, bounds):
    start, end = bounds
    if start:
        queryset = queryset.filter(created_at__gte=start)
    if end:
        queryset = queryset.filter(created_at__lte=end)
    return queryset


def _response(queryset, request, serialize, action_choices):
    page = _page_number(request)
    if page is None:
        return Response({"detail": "Page must be an integer between 1 and 100000."}, status=400)
    count = queryset.count()
    rows = queryset.order_by("-created_at", "-pk")[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    return Response({
        "count": count,
        "page": page,
        "page_size": PAGE_SIZE,
        "actions": [{"value": item.value, "label": item.label} for item in action_choices],
        "results": [serialize(row) for row in rows],
    })


def _safe_text(value, max_length=160):
    return value[:max_length] if isinstance(value, str) else ""


def _safe_resource_changes(metadata):
    results = []
    source = metadata.get("resource_changes", [])
    if not isinstance(source, list):
        return results
    for entry in source[:20]:
        if not isinstance(entry, dict):
            continue
        results.append({
            "name": _safe_text(entry.get("name"), 200),
            "kind": entry.get("kind") if entry.get("kind") in ("file", "folder") else "",
            "operation": entry.get("operation") if entry.get("operation") in
                ("created", "permission_changed", "revoked") else "unknown",
            "permission": _safe_text(entry.get("permission"), 30),
            "previous_permission": _safe_text(entry.get("previous_permission"), 30),
        })
    return results


def _share_projection(row):
    """Explicit allowlist: never return arbitrary activity metadata or description."""
    metadata = row.metadata if isinstance(row.metadata, dict) else {}
    names = metadata.get("resource_names", [])
    kinds = metadata.get("resource_kinds", [])
    valid_operations = {"created", "permission_changed", "mixed", "revoked"}
    operation = metadata.get("operation")
    if operation not in valid_operations:
        operation = "unknown"
    return {
        "operation": operation,
        "recipient": _safe_text(metadata.get("recipient_email") or metadata.get("recipient_username")),
        "recipient_username": _safe_text(metadata.get("recipient_username")),
        "permission": _safe_text(metadata.get("permission"), 30),
        "previous_permission": _safe_text(metadata.get("previous_permission"), 30),
        "resources": [_safe_text(name, 200) for name in names[:20] if isinstance(name, str)]
            if isinstance(names, list) else [],
        "resource_kinds": [_safe_text(kind, 20) for kind in kinds[:20] if kind in ("file", "folder")]
            if isinstance(kinds, list) else [],
        "count": metadata.get("shared_count") if type(metadata.get("shared_count")) is int else None,
        "created_count": metadata.get("created_count") if type(metadata.get("created_count")) is int else None,
        "updated_count": metadata.get("updated_count") if type(metadata.get("updated_count")) is int else None,
        "changes": _safe_resource_changes(metadata),
    }


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_user_activity_view(request):
    """Inspect existing regular-user events across personal and organization scopes.

    This is not a request trace or a guarantee that every action was instrumented.
    In particular, login failures without an authenticated user may be absent.
    """
    action = request.query_params.get("action", "all")
    scope = request.query_params.get("scope", "all")
    visible_actions = [choice for choice in ActivityLog.Action if choice.value != ActivityLog.Action.SEARCH]
    if action != "all" and action not in {choice.value for choice in visible_actions}:
        return Response({"detail": "Invalid activity action."}, status=400)
    if scope not in ("all", "personal", "organization", "unassigned"):
        return Response({"detail": "Invalid activity scope."}, status=400)
    bounds, error = _date_filters(request)
    if error is not None:
        return error
    query = str(request.query_params.get("q", "")).strip()[:MAX_SEARCH_LENGTH]

    events = ActivityLog.objects.filter(
        user__is_staff=False, user__is_superuser=False,
    ).exclude(action=ActivityLog.Action.SEARCH).select_related(
        "user", "tenant", "workspace", "content_type"
    )
    if action != "all":
        events = events.filter(action=action)
    if scope == "personal":
        events = events.filter(tenant__kind=Tenant.Kind.PERSONAL)
    elif scope == "organization":
        events = events.filter(tenant__kind=Tenant.Kind.BUSINESS)
    elif scope == "unassigned":
        events = events.filter(tenant__isnull=True)
    if query:
        events = events.filter(
            Q(user__username__icontains=query)
            | Q(user__email__icontains=query)
            | Q(tenant__name__icontains=query)
            | Q(workspace__name__icontains=query)
        )
    events = _apply_range(events, bounds)

    def serialize(row):
        kind = row.tenant.kind if row.tenant_id else None
        return {
            "id": str(row.pk),
            "created_at": row.created_at.isoformat(),
            "action": row.action,
            "action_label": row.get_action_display(),
            "user": row.user.get_username(),
            "user_id": row.user_id,
            "scope": ("organization" if kind == Tenant.Kind.BUSINESS else "personal" if kind == Tenant.Kind.PERSONAL else "unassigned"),
            "tenant": row.tenant.name if row.tenant_id else None,
            "workspace": (row.workspace.name if row.workspace_id and not row.workspace.is_default else None),
            "personal_drive": bool(row.workspace_id and row.workspace.is_default),
            "resource_type": row.content_type.model if row.content_type_id else None,
            "resource_id": row.object_id if row.content_type_id else None,
            "resource_name": (_safe_text(row.metadata.get("resource_name"), 200)
                if isinstance(row.metadata, dict) else ""),
            "share": (_share_projection(row) if row.action in (
                ActivityLog.Action.SHARE, ActivityLog.Action.REVOKE_SHARE
            ) else None),
        }

    return _response(events, request, serialize, visible_actions)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_audit_history_view(request):
    """Platform privilege and account changes already recorded by BlueDrive."""
    action = request.query_params.get("action", "all")
    if action != "all" and action not in PlatformAdminAuditEvent.Action.values:
        return Response({"detail": "Invalid administrative action."}, status=400)
    bounds, error = _date_filters(request)
    if error is not None:
        return error
    query = str(request.query_params.get("q", "")).strip()[:MAX_SEARCH_LENGTH]
    events = PlatformAdminAuditEvent.objects.select_related("actor", "target_user")
    if action != "all":
        events = events.filter(action=action)
    if query:
        events = events.filter(
            Q(actor__username__icontains=query)
            | Q(target_user__username__icontains=query)
            | Q(actor__email__icontains=query)
            | Q(target_user__email__icontains=query)
        )
    events = _apply_range(events, bounds)

    def serialize(row):
        return {
            "id": str(row.pk),
            "created_at": row.created_at.isoformat(),
            "action": row.action,
            "action_label": row.get_action_display(),
            "actor": row.actor.get_username(),
            "target": row.target_user.get_username(),
            "target_id": row.target_user_id,
            "reason": row.reason,
        }

    return _response(events, request, serialize, PlatformAdminAuditEvent.Action)
