"""Best-effort inventory of authenticated DB-backed sessions.

The inventory begins after this feature is installed. An unexpired Django
session is NOT proof that a user is currently online; `last_seen_at` represents
the last authenticated HTTP request observed by this middleware.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.utils import timezone

from .models import TrackedAccountSession

logger = logging.getLogger(__name__)
ONLINE_WINDOW = timedelta(minutes=5)
TRACKING_INTERVAL = timedelta(seconds=60)


def record_authenticated_session(request):
    if getattr(settings, "SESSION_ENGINE", "django.contrib.sessions.backends.db") != "django.contrib.sessions.backends.db":
        return
    user = getattr(request, "user", None)
    session_key = getattr(getattr(request, "session", None), "session_key", None)
    if not user or not user.is_authenticated or not user.is_active or not session_key:
        return
    now = timezone.now()
    try:
        session = Session.objects.filter(pk=session_key, expire_date__gt=now).first()
        if session is None:
            # First login response: SessionMiddleware has not saved its row yet.
            return
        observed, created = TrackedAccountSession.objects.get_or_create(
            session=session,
            defaults={
                "user": user,
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255],
            },
        )
        if not created and observed.user_id == user.pk and observed.last_seen_at <= now - TRACKING_INTERVAL:
            TrackedAccountSession.objects.filter(pk=observed.pk).update(last_seen_at=now)
    except DatabaseError:
        # Do not bring down every user request if migration has not run yet or
        # the optional activity inventory is temporarily unavailable.
        logger.warning("Account session tracking unavailable", exc_info=True)


def revoke_other_database_sessions(user, *, exclude_session_key=None):
    """Revoke tracked and legacy DB sessions, optionally retaining one key.

    Session has no user index in Django. For large installations, migrate to a
    complete indexed registry, including pre-tracking sessions.
    """
    keys = []
    for session in Session.objects.iterator(chunk_size=500):
        if session.pk == exclude_session_key:
            continue
        decoded = session.get_decoded()
        if str(decoded.get("_auth_user_id", "")) == str(user.pk):
            keys.append(session.pk)
    # Collect before deleting to avoid mutating a live server-side cursor.
    for start in range(0, len(keys), 500):
        Session.objects.filter(pk__in=keys[start:start + 500]).delete()
    return len(keys)


def revoke_all_database_sessions(user):
    """Revoke tracked and legacy Django DB sessions for administrative actions."""
    return revoke_other_database_sessions(user)
