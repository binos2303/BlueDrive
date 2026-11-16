"""Live admin settings: one persisted display label plus read-only runtime policy.

This API deliberately does not claim to update Django sessions, audit recording,
maintenance mode, secrets, or object-storage security settings at runtime.
"""
from django.conf import settings
from django.db import transaction
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from .admin_api import IsPlatformAdmin
from .api_views import require_csrf
from .models import PlatformAdminAuditEvent, PlatformConsoleSettings
from .platform_admin import is_platform_super_admin


DEFAULT_CONSOLE_NAME = "BlueDrive"


def _serialize(row, user):
    return {
        "display_name": row.display_name if row else DEFAULT_CONSOLE_NAME,
        "revision": row.revision if row else 0,
        "updated_at": row.updated_at.isoformat() if row else None,
        "can_edit": is_platform_super_admin(user),
        "effective_security": {
            "session_cookie_age_seconds": int(settings.SESSION_COOKIE_AGE),
            "expire_at_browser_close": bool(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE),
            "session_cookie_secure": bool(settings.SESSION_COOKIE_SECURE),
            "csrf_cookie_secure": bool(settings.CSRF_COOKIE_SECURE),
            "admin_audit": "enforced_for_supported_actions",
            "maintenance_mode": "not_configured",
        },
    }


def _validated_update(data):
    if not isinstance(data, dict) or set(data) != {"display_name", "reason", "revision"}:
        return None, "Provide only display_name, reason and revision."
    raw_name, raw_reason, revision = data["display_name"], data["reason"], data["revision"]
    if not isinstance(raw_name, str) or not isinstance(raw_reason, str):
        return None, "Display name and reason must be strings."
    name, reason = raw_name.strip(), raw_reason.strip()
    if not 2 <= len(name) <= 80 or not all(char.isprintable() for char in raw_name):
        return None, "Display name must contain 2–80 printable characters."
    if not 8 <= len(reason) <= 500 or not all(char.isprintable() for char in raw_reason):
        return None, "Reason must contain 8–500 printable characters."
    if type(revision) is not int or not 0 <= revision <= 2147483647:
        return None, "Revision must be a non-negative integer."
    return (name, reason, revision), None


@require_csrf
@api_view(["GET", "PATCH"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_settings_view(request):
    if request.method == "GET":
        row = PlatformConsoleSettings.objects.filter(pk=1).first()
        response = Response(_serialize(row, request.user))
        response["Cache-Control"] = "private, no-store"
        return response

    if not is_platform_super_admin(request.user):
        return Response({"detail": "Only Super Admin may update platform settings."}, status=403)
    validated, error = _validated_update(request.data)
    if error is not None:
        return Response({"detail": error}, status=400)
    name, reason, revision = validated

    with transaction.atomic():
        row, _ = PlatformConsoleSettings.objects.select_for_update().get_or_create(
            pk=1, defaults={"display_name": DEFAULT_CONSOLE_NAME},
        )
        if row.revision != revision:
            return Response({"detail": "Settings changed. Reload before saving again."}, status=409)
        if row.display_name != name:
            if row.revision >= 2147483647:
                return Response({"detail": "Settings revision limit reached; contact an operator."}, status=409)
            before = row.display_name
            row.display_name = name
            row.revision += 1
            row.save(update_fields=["display_name", "revision", "updated_at"])
            PlatformAdminAuditEvent.objects.create(
                actor=request.user, target_user=request.user,
                action=PlatformAdminAuditEvent.Action.SETTINGS_UPDATE,
                reason=reason,
                metadata={"field": "display_name", "before": before, "after": name},
            )

    response = Response(_serialize(row, request.user))
    response["Cache-Control"] = "private, no-store"
    return response
