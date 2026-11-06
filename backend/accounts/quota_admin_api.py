"""Platform quota inventory and controlled allocations; never exposes file content."""
import re
from django.utils.text import slugify

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Count
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts.models import (QuotaAccount, QuotaAuditEvent, StoragePlan, StoragePlanAuditEvent,
    StoragePolicy, StoragePolicyAuditEvent, Tenant, Workspace)
from accounts.admin_api import IsPlatformAdmin, active_collaboration_workspaces
from accounts.platform_admin import is_platform_super_admin
from accounts.api_views import require_csrf

PAGE_SIZE = 20
MAX_BYTES = 10 ** 17


def _page(request):
    try:
        page = int(request.query_params.get("page", "1"))
        return page if 1 <= page <= 100000 else None
    except (ValueError, TypeError):
        return None


def _summary(row, warning_percent=80, critical_percent=95):
    if row is None:
        return None
    total = row.used_bytes + row.reserved_bytes
    return {
        "id": str(row.pk), "limit_bytes": row.limit_bytes,
        "used_bytes": row.used_bytes, "reserved_bytes": row.reserved_bytes,
        "remaining_bytes": None if row.limit_bytes is None else max(0, row.limit_bytes - total),
        "percentage": None if not row.limit_bytes else round(100 * total / row.limit_bytes, 1),
        "plan_code": row.plan_id,
        "status": "over_quota" if row.limit_bytes is not None and total > row.limit_bytes else
                  "full" if row.limit_bytes is not None and total == row.limit_bytes else
                  "critical" if row.limit_bytes and total * 100 >= critical_percent * row.limit_bytes else
                  "warning" if row.limit_bytes and total * 100 >= warning_percent * row.limit_bytes else "normal",
    }


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def quota_directory_view(request):
    scope = request.query_params.get("scope", "personal")
    if scope not in ("personal", "workspace"):
        return Response({"detail": "Invalid storage scope."}, status=400)
    page = _page(request)
    if page is None:
        return Response({"detail": "Invalid page."}, status=400)
    query = str(request.query_params.get("q", "")).strip()[:100]
    sort = request.query_params.get("sort", "name_asc")
    sorts = {"name_asc", "name_desc", "newest", "oldest"}
    if sort not in sorts:
        return Response({"detail": "Invalid sort."}, status=400)
    policy = StoragePolicy.objects.filter(pk=1).first()
    warning = policy.warning_percent if policy else 80
    critical = policy.critical_percent if policy else 95
    if scope == "personal":
        tenants = Tenant.objects.filter(kind=Tenant.Kind.PERSONAL).select_related("personal_owner")
        if query:
            tenants = tenants.filter(
                Q(personal_owner__username__icontains=query) |
                Q(personal_owner__email__icontains=query)
            )
        ordering = {"name_asc": ("personal_owner__username", "pk"),
                    "name_desc": ("-personal_owner__username", "pk"),
                    "newest": ("-created_at", "pk"), "oldest": ("created_at", "pk")}[sort]
        count = tenants.count()
        rows = list(tenants.order_by(*ordering)[(page - 1) * PAGE_SIZE:page * PAGE_SIZE])
        quotas = {q.tenant_id: q for q in QuotaAccount.objects.filter(
            tenant__in=rows, scope=QuotaAccount.Scope.TENANT,
        )}
        results = [{
            "scope": "personal", "id": str(tenant.pk),
            "name": tenant.personal_owner.get_username() if tenant.personal_owner else tenant.name,
            "detail": tenant.personal_owner.email if tenant.personal_owner else "",
            "tenant_status": tenant.status,
            "quota": _summary(quotas.get(tenant.pk), warning, critical),
            "editable": True,
        } for tenant in rows]
    else:
        ws = active_collaboration_workspaces().select_related("tenant")
        if query:
            ws = ws.filter(Q(name__icontains=query) | Q(tenant__name__icontains=query))
        ordering = {"name_asc": ("name", "pk"), "name_desc": ("-name", "pk"),
                    "newest": ("-created_at", "pk"), "oldest": ("created_at", "pk")}[sort]
        count = ws.count()
        rows = list(ws.order_by(*ordering)[(page - 1) * PAGE_SIZE:page * PAGE_SIZE])
        quotas = {q.workspace_id: q for q in QuotaAccount.objects.filter(
            workspace__in=rows, scope=QuotaAccount.Scope.WORKSPACE,
        )}
        results = [{
            "scope": "workspace", "id": str(workspace.pk), "name": workspace.name,
            "detail": workspace.tenant.name, "tenant_status": workspace.tenant.status,
            "tenant_kind": workspace.tenant.kind,
            "quota": _summary(quotas.get(workspace.pk), warning, critical),
            # Business-owned storage is view-only on the platform. Enterprise
            # allocation must use separate tenant-scoped authorization.
            "editable": workspace.tenant.kind == Tenant.Kind.PERSONAL,
        } for workspace in rows]
    return Response({"count": count, "page": page, "page_size": PAGE_SIZE, "results": results})


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def quota_plans_view(request):
    include_inactive = request.query_params.get("include_inactive") == "1"
    plans = StoragePlan.objects.all()
    if not include_inactive:
        plans = plans.filter(is_active=True)
    return Response({"plans": [
        {**_plan_dict(p), "assignments": p.assignment_count}
        for p in plans.annotate(assignment_count=Count("assignments")).order_by("scope", "limit_bytes", "code")
    ]})


def _valid_limit(value):
    return type(value) is int and 0 <= value <= MAX_BYTES


@require_csrf
@api_view(["PATCH"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def quota_update_view(request, quota_id):
    """Super-admin-only write; never silently deletes or reduces stored data."""
    if not is_platform_super_admin(request.user):
        return Response({"detail": "Super Admin permission is required."}, status=403)
    data = request.data
    if not isinstance(data, dict) or set(data) != {"reason", "plan_code", "limit_bytes"}:
        return Response({"detail": "Provide reason, plan_code and limit_bytes."}, status=400)
    reason = data.get("reason")
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 500:
        return Response({"detail": "Reason must contain 8–500 characters."}, status=400)
    reason = reason.strip()
    plan_code = data.get("plan_code")
    limit = data.get("limit_bytes")
    if plan_code is not None and (not isinstance(plan_code, str) or not plan_code.strip()):
        return Response({"detail": "Invalid plan code."}, status=400)
    if plan_code is None and not _valid_limit(limit):
        return Response({"detail": "Invalid quota limit."}, status=400)
    with transaction.atomic():
        row = (
            QuotaAccount.objects
            .select_for_update()
            .filter(pk=quota_id)
            .first()
        )
        if row is None:
            return Response({"detail": "Quota account unavailable."}, status=404)
        if row.tenant.kind != Tenant.Kind.PERSONAL or row.scope not in (QuotaAccount.Scope.TENANT, QuotaAccount.Scope.WORKSPACE):
            return Response({"detail": "Organization allocations must be managed by the organization administrator."}, status=403)
        if row.scope == QuotaAccount.Scope.WORKSPACE and (row.workspace is None or row.workspace.is_default):
            return Response({"detail": "Invalid quota scope."}, status=400)
        plan = None
        if plan_code is not None:
            plan = StoragePlan.objects.filter(code=plan_code, is_active=True).first()
            if plan is None:
                return Response({"detail": "Plan unavailable."}, status=400)
            required = StoragePlan.Scope.PERSONAL if row.scope == QuotaAccount.Scope.TENANT else StoragePlan.Scope.WORKSPACE
            if plan.scope != required:
                return Response({"detail": "Plan scope mismatch."}, status=400)
            limit = plan.limit_bytes
        policy = StoragePolicy.objects.filter(pk=1).first()
        warning = policy.warning_percent if policy else 80
        critical = policy.critical_percent if policy else 95
        if row.limit_bytes == limit and row.plan_id == (plan.code if plan else None):
            return Response({"quota": _summary(row, warning, critical), "unchanged": True})
        old_limit, old_plan = row.limit_bytes, row.plan_id or ""
        row.limit_bytes = limit
        row.plan = plan
        row.save(update_fields=["limit_bytes", "plan", "updated_at"])
        QuotaAuditEvent.objects.create(
            actor=request.user, quota_account=row,
            old_limit_bytes=old_limit, new_limit_bytes=limit,
            old_plan_code=old_plan, new_plan_code=plan.code if plan else "",
            reason=reason,
        )
        return Response({"quota": _summary(row, warning, critical)})


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def quota_history_view(request):
    page = _page(request)
    if page is None:
        return Response({"detail": "Invalid page."}, status=400)
    qs = QuotaAuditEvent.objects.select_related("actor", "quota_account").order_by("-created_at", "-id")
    count = qs.count()
    rows = qs[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    return Response({"page": page, "page_size": PAGE_SIZE, "count": count, "results": [
        {"id": str(e.pk), "created_at": e.created_at, "actor": e.actor.get_username(),
         "quota_account_id": str(e.quota_account_id), "old_limit_bytes": e.old_limit_bytes,
         "new_limit_bytes": e.new_limit_bytes, "old_plan_code": e.old_plan_code,
         "new_plan_code": e.new_plan_code, "reason": e.reason}
        for e in rows
    ]})


def _reason(data):
    value = data.get("reason")
    return value.strip() if isinstance(value, str) and 8 <= len(value.strip()) <= 500 else None


def _plan_dict(plan):
    return {"code": plan.code, "name": plan.name, "scope": plan.scope,
            "limit_bytes": plan.limit_bytes, "is_active": plan.is_active}


@require_csrf
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def quota_plan_create_view(request):
    """Create a new non-billing quota preset; immutable code and scope."""
    if not is_platform_super_admin(request.user):
        return Response({"detail": "Super Admin permission is required."}, status=403)
    data = request.data
    if not isinstance(data, dict) or set(data) != {"code", "name", "scope", "limit_bytes", "reason"}:
        return Response({"detail": "Invalid plan fields."}, status=400)
    code, name, scope, limit = data["code"], data["name"], data["scope"], data["limit_bytes"]
    if (not isinstance(code, str) or not 2 <= len(code) <= 48 or slugify(code) != code or
            not isinstance(name, str) or not 2 <= len(name.strip()) <= 80 or
            scope not in (StoragePlan.Scope.PERSONAL, StoragePlan.Scope.WORKSPACE) or
            not _valid_limit(limit) or not _reason(data)):
        return Response({"detail": "Invalid code, name, scope, limit or reason."}, status=400)
    with transaction.atomic():
        if StoragePlan.objects.filter(pk=code).exists():
            return Response({"detail": "Plan code already exists."}, status=409)
        plan = StoragePlan.objects.create(code=code, name=name.strip(), scope=scope, limit_bytes=limit)
        StoragePlanAuditEvent.objects.create(actor=request.user, plan_code=code,
            action="created", before={}, after=_plan_dict(plan), reason=_reason(data))
    return Response({"plan": _plan_dict(plan)}, status=201)


@require_csrf
@api_view(["PATCH"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def quota_plan_update_view(request, code):
    if not is_platform_super_admin(request.user):
        return Response({"detail": "Super Admin permission is required."}, status=403)
    data = request.data
    if not isinstance(data, dict) or set(data) != {"name", "limit_bytes", "is_active", "reason"}:
        return Response({"detail": "Invalid plan fields."}, status=400)
    if (not isinstance(data["name"], str) or not 2 <= len(data["name"].strip()) <= 80 or
            not _valid_limit(data["limit_bytes"]) or type(data["is_active"]) is not bool or not _reason(data)):
        return Response({"detail": "Invalid plan values or reason."}, status=400)
    with transaction.atomic():
        plan = StoragePlan.objects.select_for_update().filter(pk=code).first()
        if plan is None:
            return Response({"detail": "Plan unavailable."}, status=404)
        if code in {"free", "workspace-starter"} and data["is_active"] is False:
            return Response({"detail": "Baseline plans must remain active."}, status=409)
        before = _plan_dict(plan)
        plan.name = data["name"].strip()
        plan.limit_bytes = data["limit_bytes"]
        plan.is_active = data["is_active"]
        after = _plan_dict(plan)
        if before != after:
            plan.save(update_fields=["name", "limit_bytes", "is_active", "updated_at"])
            StoragePlanAuditEvent.objects.create(actor=request.user, plan_code=code,
                action="updated", before=before, after=after, reason=_reason(data))
    # Existing allocations preserve their limit_bytes. Future plan assignments use the new preset.
    return Response({"plan": after, "existing_allocations_unchanged": True})



# The two baseline presets always stay available. Additional presets are
# removable when unused; assignments to legacy presets are never erased.
BASELINE_PLANS = frozenset({"free", "workspace-starter"})


@require_csrf
@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def quota_plan_delete_view(request, code):
    if not is_platform_super_admin(request.user):
        return Response({"detail": "Super Admin permission is required."}, status=403)
    data = request.data
    if not isinstance(data, dict) or set(data) != {"reason"} or not _reason(data):
        return Response({"detail": "Reason must contain 8–500 characters."}, status=400)
    if code in BASELINE_PLANS:
        return Response({"detail": "Free and Workspace Starter are protected baseline plans."}, status=409)
    with transaction.atomic():
        plan = StoragePlan.objects.select_for_update().filter(pk=code).first()
        if plan is None:
            return Response({"detail": "Plan unavailable."}, status=404)
        if QuotaAccount.objects.filter(plan_id=code).exists():
            return Response({"detail": "Plan is assigned to quota accounts. Disable it first; existing allocations must be preserved."}, status=409)
        before = _plan_dict(plan)
        # Audit must not FK to the deleted plan; only the code and snapshot remain.
        plan.delete()
        StoragePlanAuditEvent.objects.create(
            actor=request.user, plan_code=code, action="deleted",
            before=before, after={}, reason=_reason(data),
        )
    return Response(status=204)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def quota_policy_view(request):
    policy = StoragePolicy.objects.filter(pk=1).first()
    return Response({"warning_percent": policy.warning_percent if policy else 80,
                     "critical_percent": policy.critical_percent if policy else 95})


@require_csrf
@api_view(["PATCH"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def quota_policy_update_view(request):
    if not is_platform_super_admin(request.user):
        return Response({"detail": "Super Admin permission is required."}, status=403)
    data = request.data
    if not isinstance(data, dict) or set(data) != {"warning_percent", "critical_percent", "reason"} or not _reason(data):
        return Response({"detail": "Invalid quota policy fields or reason."}, status=400)
    warning, critical = data["warning_percent"], data["critical_percent"]
    if type(warning) is not int or type(critical) is not int or not 1 <= warning < critical <= 100:
        return Response({"detail": "Require 1 <= warning < critical <= 100."}, status=400)
    with transaction.atomic():
        StoragePolicy.objects.get_or_create(pk=1)
        policy = StoragePolicy.objects.select_for_update().get(pk=1)
        before = {"warning_percent": policy.warning_percent, "critical_percent": policy.critical_percent}
        after = {"warning_percent": warning, "critical_percent": critical}
        if before != after:
            policy.warning_percent = warning
            policy.critical_percent = critical
            policy.save(update_fields=["warning_percent", "critical_percent", "updated_at"])
            StoragePolicyAuditEvent.objects.create(
                actor=request.user, old_limit=None, new_limit=None,
                before=before, after=after, reason=_reason(data),
            )
    return Response(after)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def quota_configuration_history_view(request):
    page = _page(request)
    if page is None:
        return Response({"detail": "Invalid page."}, status=400)
    plans = StoragePlanAuditEvent.objects.select_related("actor").order_by("-created_at")[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    policies = StoragePolicyAuditEvent.objects.select_related("actor").order_by("-created_at")[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    return Response({
        "plan_change_count": StoragePlanAuditEvent.objects.count(),
        "policy_change_count": StoragePolicyAuditEvent.objects.count(),
        "plan_changes": [{"id": str(item.pk), "created_at": item.created_at, "actor": item.actor.get_username(),
                          "target": item.plan_code, "action": item.action, "reason": item.reason} for item in plans],
        "policy_changes": [{"id": str(item.pk), "created_at": item.created_at, "actor": item.actor.get_username(),
                            "reason": item.reason, "old_limit": item.old_limit, "new_limit": item.new_limit} for item in policies],
    })
