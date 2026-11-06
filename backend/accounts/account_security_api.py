"""Self-service security APIs backed by Django sessions and password validators."""
import logging

from django.conf import settings
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .api_views import require_csrf
from .models import TrackedAccountSession
from .session_tracking import record_authenticated_session, revoke_other_database_sessions

logger = logging.getLogger(__name__)


def _session_backend_supported():
    return getattr(settings, "SESSION_ENGINE", "django.contrib.sessions.backends.db") == "django.contrib.sessions.backends.db"


def _session_backend_error():
    return Response({"detail": "Session management requires Django database-backed sessions."}, status=503)


def _password_error():
    return Response({"detail": "The current password is incorrect.", "fieldErrors": {
        "current_password": ["The current password is incorrect."]
    }}, status=403)


def _verify_password(request):
    password = request.data.get("current_password") if isinstance(request.data, dict) else None
    return isinstance(password, str) and request.user.check_password(password)


@require_csrf
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def change_password_view(request):
    if not _session_backend_supported():
        return _session_backend_error()
    required = {"old_password", "new_password1", "new_password2"}
    if not isinstance(request.data, dict) or set(request.data) != required:
        return Response({"detail": "Current password, new password and confirmation are required."}, status=400)
    if any(not isinstance(request.data[name], str) or len(request.data[name]) > 4096 for name in required):
        return Response({"detail": "Invalid password fields."}, status=400)
    if request.data["new_password1"] == request.data["old_password"]:
        return Response({"detail": "Choose a different password.", "fieldErrors": {
            "new_password1": ["The new password must differ from the current password."]
        }}, status=400)
    form = PasswordChangeForm(request.user, request.data)
    if not form.is_valid():
        errors = {key: [message["message"] for message in values]
                  for key, values in form.errors.get_json_data().items()}
        return Response({"detail": "Check the password fields.", "fieldErrors": errors}, status=400)

    user = form.save()
    # Rotate the current key while preserving this authenticated browser. Other
    # keys are revoked, including legacy sessions not yet observed by tracking.
    update_session_auth_hash(request, user)
    revoked = revoke_other_database_sessions(user, exclude_session_key=request.session.session_key)
    logger.info("Account password changed user_id=%s revoked_other_sessions=%s", user.pk, revoked)
    response = Response({"changed": True, "otherSessionsRevoked": revoked})
    response["Cache-Control"] = "no-store"
    return response


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def my_sessions_view(request):
    if not _session_backend_supported():
        return _session_backend_error()
    try:
        page = int(request.query_params.get("page", 1))
    except (TypeError, ValueError):
        return Response({"detail": "Invalid page number."}, status=400)
    if not 1 <= page <= 10000:
        return Response({"detail": "Invalid page number."}, status=400)
    # The first account-security request may be the first authenticated request
    # since login; ensure it can appear in the tracking inventory immediately.
    record_authenticated_session(request)
    now = timezone.now()
    queryset = TrackedAccountSession.objects.filter(
        user=request.user, session__expire_date__gt=now
    ).select_related("session").order_by("-last_seen_at", "-pk")
    count = queryset.count()
    rows = queryset[(page - 1) * 20:page * 20]
    response = Response({
        "count": count, "page": page, "pageSize": 20,
        "note": "Only sessions observed since session tracking was enabled appear here. Last activity is not proof of being online.",
        "sessions": [{
            "id": str(row.pk),
            "current": row.session_id == request.session.session_key,
            "startedAt": row.started_at.isoformat(),
            "lastSeenAt": row.last_seen_at.isoformat(),
            "expiresAt": row.session.expire_date.isoformat(),
            "userAgent": row.user_agent,
        } for row in rows],
    })
    response["Cache-Control"] = "private, no-store"
    return response


@require_csrf
@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def revoke_my_session_view(request, session_id):
    if not _session_backend_supported():
        return _session_backend_error()
    if not _verify_password(request):
        return _password_error()
    with transaction.atomic():
        row = TrackedAccountSession.objects.select_for_update().filter(
            pk=session_id, user=request.user, session__expire_date__gt=timezone.now()
        ).first()
        if row is None:
            return Response({"detail": "Session not found."}, status=404)
        current = row.session_id == request.session.session_key
        if not current:
            Session.objects.filter(pk=row.session_id).delete()
    if current:
        logout(request)
    logger.info("Account session revoked user_id=%s self_revoked=%s", request.user.pk if not current else row.user_id, current)
    response = Response({"revoked": True, "signedOut": current})
    response["Cache-Control"] = "no-store"
    return response


@require_csrf
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def revoke_other_sessions_view(request):
    if not _session_backend_supported():
        return _session_backend_error()
    if not isinstance(request.data, dict) or set(request.data) != {"current_password"}:
        return Response({"detail": "Current password is required."}, status=400)
    if not _verify_password(request):
        return _password_error()
    count = revoke_other_database_sessions(
        request.user, exclude_session_key=request.session.session_key
    )
    logger.info("Other account sessions revoked user_id=%s count=%s", request.user.pk, count)
    response = Response({"revoked": count})
    response["Cache-Control"] = "no-store"
    return response
