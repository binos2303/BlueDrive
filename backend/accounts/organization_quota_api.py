"""Tenant-scoped organization quota allocations. No cross-tenant administration."""
from django.db import transaction
from django.core.exceptions import ValidationError
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.api_views import require_csrf
from accounts.access import active_membership
from accounts.models import Membership, QuotaAccount, QuotaAuditEvent, Tenant, Workspace
from accounts.quota_admin_api import MAX_BYTES, _summary


def _administrator(user, tenant_id):
    tenant = Tenant.objects.filter(
        pk=tenant_id, kind=Tenant.Kind.BUSINESS, status=Tenant.Status.ACTIVE,
    ).first()
    if tenant is None or not getattr(user, "is_active", False):
        return None
    member = active_membership(user, tenant.pk)
    return tenant if member is not None and member.role in (Membership.Role.OWNER, Membership.Role.ADMIN) else None


@require_csrf
@api_view(["GET", "PATCH"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def organization_quota_view(request, tenant_id):
    tenant = _administrator(request.user, tenant_id)
    if tenant is None:
        return Response({"detail": "Organization quota is unavailable."}, status=404)
    if request.method == "GET":
        rows = QuotaAccount.objects.filter(tenant=tenant).select_related("user", "workspace").order_by("scope", "id")
        return Response({"quotas": [
            {"scope": q.scope,
             "target_id": str(q.workspace_id or q.user_id or tenant.pk),
             "target": q.workspace.name if q.workspace_id else q.user.get_username() if q.user_id else tenant.name,
             "quota": _summary(q)}
            for q in rows
        ]})
    data = request.data
    if not isinstance(data, dict) or set(data) != {"scope", "target_id", "limit_bytes", "reason"}:
        return Response({"detail": "Provide scope, target_id, limit_bytes and reason."}, status=400)
    scope = data["scope"]
    if scope not in ("tenant", "member", "workspace"):
        return Response({"detail": "Invalid quota scope."}, status=400)
    limit = data["limit_bytes"]
    if type(limit) is not int or not 0 <= limit <= MAX_BYTES:
        return Response({"detail": "Invalid quota limit."}, status=400)
    reason = data["reason"]
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 500:
        return Response({"detail": "Reason must contain 8–500 characters."}, status=400)
    reason = reason.strip()
    target = str(data["target_id"])
    with transaction.atomic():
        if scope == "tenant":
            if target != str(tenant.pk):
                return Response({"detail": "Quota target unavailable."}, status=404)
            q, _ = QuotaAccount.objects.get_or_create(
                tenant=tenant, scope=QuotaAccount.Scope.TENANT,
                defaults={"limit_bytes": 0},
            )
        elif scope == "member":
            try:
                member_id = int(target)
            except (ValueError, TypeError):
                return Response({"detail": "Invalid member ID."}, status=400)
            membership = Membership.objects.filter(tenant=tenant, user_id=member_id, status=Membership.Status.ACTIVE).first()
            if membership is None:
                return Response({"detail": "Organization member unavailable."}, status=404)
            q, _ = QuotaAccount.objects.get_or_create(
                tenant=tenant, user=membership.user, scope=QuotaAccount.Scope.MEMBER,
                defaults={"limit_bytes": 0},
            )
        else:
            try:
                workspace = Workspace.objects.filter(pk=target, tenant=tenant, is_default=False, owned_identity__isnull=True).first()
            except (ValueError, ValidationError):
                return Response({"detail": "Invalid workspace ID."}, status=400)
            if workspace is None:
                return Response({"detail": "Workspace unavailable."}, status=404)
            q = QuotaAccount.objects.filter(tenant=tenant, workspace=workspace, scope=QuotaAccount.Scope.WORKSPACE).first()
            if q is None:
                return Response({"detail": "Reconcile legacy workspace quota before editing."}, status=409)
        q = QuotaAccount.objects.select_for_update().get(pk=q.pk)
        old, old_plan = q.limit_bytes, q.plan_id or ""
        if old == limit:
            return Response({"quota": _summary(q), "unchanged": True})
        q.limit_bytes = limit
        q.plan = None
        q.save(update_fields=["limit_bytes", "plan", "updated_at"])
        QuotaAuditEvent.objects.create(
            actor=request.user, quota_account=q, old_limit_bytes=old,
            new_limit_bytes=limit, old_plan_code=old_plan,
            new_plan_code="", reason=reason,
        )
        return Response({"quota": _summary(q)})
