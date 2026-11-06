"""Best-effort inventory of authenticated DB-backed sessions.

The inventory begins after this feature is installed. An unexpired Django
session is NOT proof that a user is currently online; `last_seen_at` represents
the last authenticated HTTP request observed by this middleware.
"""
import logging
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.utils import timezone

from .models import TrackedAccountSession

logger = logging.getLogger(__name__)
ONLINE_WINDOW = timedelta(minutes=5)
TRACKING_INTERVAL = timedelta(seconds=60)


def record_authenticated_session(request):
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


def revoke_all_database_sessions(user):
    """Revoke tracked AND legacy Django database sessions for a user.

    Scan is needed because Django's default Session model lacks a user index.
    For large deployments replace this with an indexed session registry and a
    complete migration/backfill plan. Do not silently skip older sessions.
    """
    keys = []
    for session in Session.objects.iterator(chunk_size=500):
        decoded = session.get_decoded()
        if str(decoded.get("_auth_user_id", "")) == str(user.pk):
            keys.append(session.pk)
    # Avoid mutating a QuerySet while its server-side cursor is still open.
    for start in range(0, len(keys), 500):
        Session.objects.filter(pk__in=keys[start:start + 500]).delete()
