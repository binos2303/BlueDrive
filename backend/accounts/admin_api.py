"""Read-only, platform-admin-only API. No account mutations are exposed."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.db.models import Count, Q, Sum
from accounts.models import Tenant, Workspace, TrackedAccountSession, PlatformAdminAuditEvent
from files.models import File
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from .platform_admin import is_platform_admin, is_platform_super_admin, platform_role
from .api_views import require_csrf
from .session_tracking import ONLINE_WINDOW, revoke_all_database_sessions


def active_collaboration_workspaces():
    """Visible collaboration areas, excluding tenant-internal My Drive/default rows.

    Keep this as the single source for both the directory and dashboard counts.
    No database records are deleted or modified.
    """
    return Workspace.objects.filter(
        is_default=False,
        status=Workspace.Status.ACTIVE,
        tenant__status=Tenant.Status.ACTIVE,
    )


class IsPlatformAdmin(BasePermission):
    def has_permission(self, request, view):
        return is_platform_admin(request.user)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_access_view(request):
    user = request.user
    return Response({"allowed": True, "username": user.get_username(), "email": user.email, "role": platform_role(user), "can_manage_admins": is_platform_super_admin(user)})


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_users_view(request):
    """Read-only account directory; the admin/user classification matches dedicated RBAC."""
    query = str(request.query_params.get("q", "")).strip()[:100]
    scope = str(request.query_params.get("scope", "all"))
    status = str(request.query_params.get("status", "all"))
    users = get_user_model().objects.all()
    admin_filter = Q(is_staff=True) & (Q(is_superuser=True) | Q(platform_admin_identity__isnull=False))
    if scope == "users":
        users = users.filter(is_staff=False, is_superuser=False)
    elif scope == "admins":
        users = users.filter(admin_filter).select_related("platform_admin_identity")
    elif scope != "all":
        return Response({"detail": "Invalid scope."}, status=400)
    if status == "active":
        users = users.filter(is_active=True)
    elif status == "inactive":
        users = users.filter(is_active=False)
    elif status != "all":
        return Response({"detail": "Invalid status."}, status=400)
    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
    count = users.count()
    page = _requested_page(request)
    results = list(users.order_by("pk")[(page - 1) * 20:page * 20])
    online_ids = set(TrackedAccountSession.objects.filter(
        user_id__in=[user.pk for user in results],
        last_seen_at__gte=timezone.now() - ONLINE_WINDOW,
        user__is_active=True,
        session__expire_date__gt=timezone.now(),
    ).values_list("user_id", flat=True))
    return Response({"count": count, "page": page, "page_size": 20, "results": [
        {"id": user.pk, "username": user.get_username(), "email": user.email,
         "is_active": user.is_active, "is_staff": user.is_staff,
         "is_superuser": user.is_superuser,
         "last_login": user.last_login.isoformat() if user.last_login else None,
         "date_joined": user.date_joined.isoformat() if user.date_joined else None,
         "recently_online": user.pk in online_ids,
         "admin_role": ("super_admin" if user.is_superuser else "platform_admin" if hasattr(user, "platform_admin_identity") else None),
         "admin_status": ("active" if user.is_superuser and user.is_active else "disabled" if user.is_superuser else
                          user.platform_admin_identity.status if hasattr(user, "platform_admin_identity") else None)}
        for user in results
    ]})


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_overview_view(request):
    """Read-only platform metrics from PostgreSQL; no infrastructure telemetry claims.

    Active accounts are enabled for login, NOT necessarily online sessions.
    File bytes reflect current, non-trashed metadata, NOT MinIO disk consumption.
    """
    User = get_user_model()
    admin_filter = Q(is_staff=True) & (Q(is_superuser=True) | Q(platform_admin_identity__isnull=False))
    users = User.objects.all()
    normal_users = users.filter(is_staff=False, is_superuser=False)
    businesses = Tenant.objects.filter(kind=Tenant.Kind.BUSINESS)
    workspaces = active_collaboration_workspaces()
    live_files = File.objects.filter(deleted_at__isnull=True)
    file_stats = live_files.aggregate(bytes=Sum("file_size"), count=Count("id"))
    return Response({
        "users": {
            "total": normal_users.count(),
            "active": normal_users.filter(is_active=True).count(),
            "inactive": normal_users.filter(is_active=False).count(),
            "platform_admins": users.filter(admin_filter).count(),
            "recently_seen": TrackedAccountSession.objects.filter(
                user__is_staff=False, user__is_superuser=False, user__is_active=True,
                last_seen_at__gte=timezone.now() - ONLINE_WINDOW,
                session__expire_date__gt=timezone.now(),
            ).values("user_id").distinct().count(),
        },
        "organizations": {
            "total": businesses.count(),
            "active": businesses.filter(status=Tenant.Status.ACTIVE).count(),
        },
        "workspaces": {
            "total": workspaces.count(),
            "active": workspaces.count(),
            "organization": workspaces.filter(tenant__kind=Tenant.Kind.BUSINESS).count(),
            "personal": workspaces.filter(tenant__kind=Tenant.Kind.PERSONAL).count(),
        },
        "files": {
            "total": file_stats["count"],
            "metadata_bytes": file_stats["bytes"] or 0,
            "in_trash": File.objects.filter(deleted_at__isnull=False).count(),
        },
        "health": {"api": "responding", "database": "responding", "minio": "not_monitored"},
    })


def _requested_page(request):
    try:
        return max(1, min(100000, int(request.query_params.get("page", "1"))))
    except (ValueError, TypeError):
        return 1


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_organizations_view(request):
    """Read-only organization directory; never exposes tenant-owned content."""
    queryset = Tenant.objects.filter(kind=Tenant.Kind.BUSINESS)
    query = str(request.query_params.get("q", "")).strip()[:100]
    if query:
        queryset = queryset.filter(name__icontains=query)
    queryset = queryset.annotate(workspace_count=Count(
        "workspaces",
        filter=Q(
            status=Tenant.Status.ACTIVE,
            workspaces__is_default=False,
            workspaces__status=Workspace.Status.ACTIVE,
        ),
        distinct=True,
    ))
    page = _requested_page(request)
    count = queryset.count()
    results = queryset.order_by("-created_at", "pk")[(page - 1) * 20:page * 20]
    return Response({"count": count, "page": page, "page_size": 20, "results": [
        {"id": str(tenant.pk), "name": tenant.name, "status": tenant.status,
         "workspaces": tenant.workspace_count,
         "created_at": tenant.created_at.isoformat()}
        for tenant in results
    ]})


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_workspaces_view(request):
    """List active collaboration workspaces; never expose internal default rows."""
    queryset = active_collaboration_workspaces().select_related("tenant")
    query = str(request.query_params.get("q", "")).strip()[:100]
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(tenant__name__icontains=query))
    page = _requested_page(request)
    count = queryset.count()
    results = queryset.order_by("-created_at", "pk")[(page - 1) * 20:page * 20]
    return Response({"count": count, "page": page, "page_size": 20, "results": [
        {"id": str(workspace.pk), "name": workspace.name, "status": workspace.status,
         "organization": workspace.tenant.name if workspace.tenant.kind == Tenant.Kind.BUSINESS else None,
         "scope": "organization" if workspace.tenant.kind == Tenant.Kind.BUSINESS else "personal",
         "created_at": workspace.created_at.isoformat()}
        for workspace in results
    ]})


# --- Phase 02: account lifecycle, observed sessions and platform audit ---

def _db_sessions_supported():
    return getattr(settings, "SESSION_ENGINE", "django.contrib.sessions.backends.db") == "django.contrib.sessions.backends.db"


def _validated_reason(request):
    if not isinstance(request.data, dict) or set(request.data) != {"reason"}:
        return None
    reason = request.data.get("reason")
    if not isinstance(reason, str):
        return None
    reason = reason.strip()
    return reason if 8 <= len(reason) <= 500 else None


def _require_reason(request):
    reason = _validated_reason(request)
    if reason is None:
        return None, Response({"detail": "Provide a reason of 8–500 characters."}, status=400)
    return reason, None


def _regular_account(user, actor):
    # Do not mutate ANY staff/superuser via this user management endpoint,
    # even if a misconfigured staff account is not a dedicated platform admin.
    return user.pk != actor.pk and not user.is_staff and not user.is_superuser


@require_csrf
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_suspend_user_view(request, user_id):
    reason, error = _require_reason(request)
    if error is not None:
        return error
    if not _db_sessions_supported():
        return Response({"detail": "Session revocation requires Django database sessions."}, status=503)
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().filter(pk=user_id).first()
        if user is None:
            return Response({"detail": "Account not found."}, status=404)
        if not _regular_account(user, request.user):
            return Response({"detail": "Protected administrator/staff account."}, status=403)
        if not user.is_active:
            return Response({"detail": "Account is already disabled."}, status=409)
        user.is_active = False
        user.save(update_fields=["is_active"])
        # Includes sessions created before session tracking was installed.
        revoke_all_database_sessions(user)
        PlatformAdminAuditEvent.objects.create(
            actor=request.user, target_user=user,
            action=PlatformAdminAuditEvent.Action.SUSPEND, reason=reason,
        )
    return Response({"id": user.pk, "is_active": False})


@require_csrf
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_reactivate_user_view(request, user_id):
    reason, error = _require_reason(request)
    if error is not None:
        return error
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().filter(pk=user_id).first()
        if user is None:
            return Response({"detail": "Account not found."}, status=404)
        if not _regular_account(user, request.user):
            return Response({"detail": "Protected administrator/staff account."}, status=403)
        if user.is_active:
            return Response({"detail": "Account is already enabled."}, status=409)
        user.is_active = True
        user.save(update_fields=["is_active"])
        PlatformAdminAuditEvent.objects.create(
            actor=request.user, target_user=user,
            action=PlatformAdminAuditEvent.Action.REACTIVATE, reason=reason,
        )
    return Response({"id": user.pk, "is_active": True})


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_sessions_view(request):
    """Observed, unexpired DB sessions; recent activity is not a presence ping."""
    if not _db_sessions_supported():
        return Response({"detail": "Session listing requires Django database sessions."}, status=503)
    scope = request.query_params.get("scope", "users")
    presence = request.query_params.get("presence", "all")
    if scope not in ("users", "admins", "all") or presence not in ("all", "recent"):
        return Response({"detail": "Invalid session filters."}, status=400)
    now = timezone.now()
    queryset = TrackedAccountSession.objects.select_related("user", "session").filter(session__expire_date__gt=now)
    if scope == "users":
        queryset = queryset.exclude(user__is_staff=True, user__is_superuser=True)
    elif scope == "admins":
        queryset = queryset.filter(user__is_staff=True, user__is_superuser=True)
    if presence == "recent":
        queryset = queryset.filter(last_seen_at__gte=now - ONLINE_WINDOW)
    user_id = str(request.query_params.get("user_id", "")).strip()
    if user_id:
        if not user_id.isdecimal() or len(user_id) > 18:
            return Response({"detail": "Invalid user ID."}, status=400)
        queryset = queryset.filter(user_id=user_id)
    count = queryset.count()
    page = _requested_page(request)
    rows = queryset.order_by("-last_seen_at", "pk")[(page - 1) * 20:page * 20]
    return Response({
        "count": count, "page": page, "page_size": 20,
        "tracking_note": "Only sessions observed since tracking was deployed are shown. An unexpired session is not necessarily online.",
        "results": [{
            "id": str(row.pk), "user_id": row.user_id,
            "username": row.user.get_username(),
            "account_type": ("admin" if row.user.is_staff and row.user.is_superuser
                             else "staff" if row.user.is_staff or row.user.is_superuser else "user"),
            "started_at": row.started_at.isoformat(),
            "last_seen_at": row.last_seen_at.isoformat(),
            "expires_at": row.session.expire_date.isoformat(),
            "recently_online": row.user.is_active and row.last_seen_at >= now - ONLINE_WINDOW,
            "user_agent": row.user_agent,
            "can_revoke": not row.user.is_staff and not row.user.is_superuser,
        } for row in rows],
    })


@require_csrf
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_revoke_session_view(request, session_id):
    reason, error = _require_reason(request)
    if error is not None:
        return error
    if not _db_sessions_supported():
        return Response({"detail": "Session revocation requires Django database sessions."}, status=503)
    with transaction.atomic():
        row = TrackedAccountSession.objects.select_for_update().select_related("user", "session").filter(pk=session_id).first()
        if row is None:
            return Response({"detail": "Tracked session not found."}, status=404)
        if not _regular_account(row.user, request.user):
            return Response({"detail": "Administrator/staff sessions are protected."}, status=403)
        target_user = row.user
        session_row = row.session
        session_row.delete()
        PlatformAdminAuditEvent.objects.create(
            actor=request.user, target_user=target_user,
            action=PlatformAdminAuditEvent.Action.REVOKE_SESSION,
            reason=reason, metadata={"session_inventory_id": str(session_id)},
        )
    return Response({"revoked": True})


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_audit_view(request):
    action = str(request.query_params.get("action", "all"))
    allowed = {"all", *PlatformAdminAuditEvent.Action.values}
    if action not in allowed:
        return Response({"detail": "Invalid audit filter."}, status=400)
    queryset = PlatformAdminAuditEvent.objects.select_related("actor", "target_user")
    if action != "all":
        queryset = queryset.filter(action=action)
    query = str(request.query_params.get("q", "")).strip()[:100]
    if query:
        queryset = queryset.filter(
            Q(actor__username__icontains=query) | Q(target_user__username__icontains=query)
        )
    count = queryset.count()
    page = _requested_page(request)
    rows = queryset.order_by("-created_at", "-pk")[(page - 1) * 20:page * 20]
    return Response({"count": count, "page": page, "page_size": 20, "results": [{
        "id": str(row.pk), "action": row.action,
        "actor": row.actor.get_username(), "target": row.target_user.get_username(),
        "target_id": row.target_user_id, "reason": row.reason,
        "created_at": row.created_at.isoformat(), "metadata": row.metadata,
    } for row in rows]})
