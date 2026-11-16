"""Shared email-update rules for JSON and legacy account views."""
import hashlib

from django.contrib.auth import get_user_model
from django.db import connection, transaction


class EmailUpdateDenied(Exception):
    def __init__(self, detail, *, status=400, field="email"):
        self.detail = detail
        self.status = status
        self.field = field
        super().__init__(detail)


def lock_email_identity(email):
    """Serialize application email writes across PostgreSQL workers.

    All account-creation/email-update paths must take this lock inside an
    atomic transaction. This is not a substitute for a database UNIQUE index
    if external writers are allowed to mutate auth_user.
    """
    if connection.vendor != "postgresql":
        return
    key = int.from_bytes(
        hashlib.sha256(email.strip().casefold().encode("utf-8")).digest()[:8],
        byteorder="big", signed=True,
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def update_user_email(user, email, current_password):
    """Reauthenticate before changing the login identity; reject known duplicates.

    Does not verify ownership of the destination address. That requires a
    separate email-verification workflow before production use.
    """
    if not isinstance(current_password, str) or not user.check_password(current_password):
        raise EmailUpdateDenied("The current password is incorrect.", status=403, field="current_password")
    normalized = email.strip()
    User = get_user_model()
    with transaction.atomic():
        lock_email_identity(normalized)
        locked = User.objects.select_for_update().get(pk=user.pk)
        if locked.email == normalized:
            return False
        # Login requires exactly one account for an email; never knowingly create
        # an ambiguous login identity. The advisory lock serializes this write
        # with registration and platform-admin provisioning.
        if User.objects.filter(email__iexact=normalized).exclude(pk=user.pk).exists():
            raise EmailUpdateDenied("This email address is already in use.", status=409)
        locked.email = normalized
        locked.save(update_fields=["email"])
        user.email = normalized
    return True
