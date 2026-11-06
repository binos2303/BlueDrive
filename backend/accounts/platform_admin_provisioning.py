"""Provision dedicated platform administrators without promoting Drive users.

Only existing Django staff superusers (Super Admins) can provision or disable.
Invitations are emailed, never returned as a token in API responses or logs.
"""
import logging
from smtplib import SMTPException
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.forms import EmailField
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response

from .api_views import require_csrf
from .models import PlatformAdminAuditEvent, PlatformAdminIdentity
from .platform_admin import is_platform_super_admin
from .session_tracking import revoke_all_database_sessions

logger = logging.getLogger(__name__)


class SuperAdminOnly(BasePermission):
    def has_permission(self, request, view):
        return is_platform_super_admin(request.user)


def _reason_from(body):
    if not isinstance(body, dict):
        return None
    reason = body.get("reason")
    if not isinstance(reason, str):
        return None
    reason = reason.strip()
    return reason if 8 <= len(reason) <= 500 else None


def _email_administrator_invitation(user):
    """Send only by an explicitly configured email backend; never return tokens."""
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_str(user.pk).encode())
    link = f"{settings.NEXTJS_FRONTEND_URL}/admin-invite?{urlencode({'uid': uid, 'token': token})}"
    send_mail(
        subject="Activate your BlueDrive Platform Administrator account",
        message=(
            f"You have been invited to BlueDrive as a Platform Administrator.\n\n"
            f"Account: {user.get_username()}\n"
            f"Set your password using this one-time link:\n{link}\n\n"
            f"If you did not expect this invitation, ignore the message. "
            f"The link expires automatically."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email], fail_silently=False,
    )


def _email_configuration_error():
    if not getattr(settings, "ADMIN_INVITES_ENABLED", False):
        return Response({"detail": "Administrator invitations are not configured."}, status=503)
    if not getattr(settings, "NEXTJS_FRONTEND_URL", "") or not getattr(settings, "DEFAULT_FROM_EMAIL", ""):
        return Response({"detail": "Administrator invitation email settings are incomplete."}, status=503)
    if not settings.DEBUG and settings.EMAIL_BACKEND in {
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.filebased.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.dummy.EmailBackend",
    }:
        return Response({"detail": "A secure email transport is required in production."}, status=503)
    return None


@require_csrf
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([SuperAdminOnly])
def invite_platform_administrator_view(request):
    config_error = _email_configuration_error()
    if config_error is not None:
        return config_error
    body = request.data
    if not isinstance(body, dict) or set(body) != {"username", "email", "reason"}:
        return Response({"detail": "Provide only username, email and reason."}, status=400)
    reason = _reason_from(body)
    if reason is None:
        return Response({"detail": "Provide a reason of 8–500 characters."}, status=400)
    username = body.get("username")
    email = body.get("email")
    if not isinstance(username, str) or not isinstance(email, str):
        return Response({"detail": "Invalid username or email."}, status=400)
    username, email = username.strip(), email.strip().lower()
    User = get_user_model()
    if not 3 <= len(username) <= User._meta.get_field(User.USERNAME_FIELD).max_length:
        return Response({"detail": "Username must have at least 3 characters."}, status=400)
    try:
        UnicodeUsernameValidator()(username)
        email = EmailField(max_length=254).clean(email)
    except ValidationError:
        return Response({"detail": "Invalid username or email."}, status=400)
    if User.objects.filter(username__iexact=username).exists() or User.objects.filter(email__iexact=email).exists():
        return Response({"detail": "The username or email is already registered. Create a separate administrator identity."}, status=409)

    # No plaintext password, no promotion of an existing Drive account.
    try:
        with transaction.atomic():
            new_user = User.objects.create_user(
                username=username, email=email, password=None,
                is_active=False, is_staff=True, is_superuser=False,
            )
            identity = PlatformAdminIdentity.objects.create(
                user=new_user, invited_by=request.user, status=PlatformAdminIdentity.Status.INVITED,
            )
            _email_administrator_invitation(new_user)
            PlatformAdminAuditEvent.objects.create(
                actor=request.user, target_user=new_user,
                action=PlatformAdminAuditEvent.Action.INVITE_ADMIN,
                reason=reason,
                metadata={"delivery": "email", "role": "platform_admin"},
            )
    except IntegrityError:
        return Response({"detail": "Account already exists."}, status=409)
    except (SMTPException, OSError, ConnectionError):
        logger.warning("Administrator invitation mail delivery failed (no token logged).")
        return Response({"detail": "Could not deliver the invitation. Check the email configuration and retry."}, status=503)
    return Response({
        "id": new_user.pk, "username": new_user.get_username(),
        "email": email, "role": "platform_admin", "status": identity.status,
        "delivery": "email",
    }, status=201)


@require_csrf
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([SuperAdminOnly])
def reinvite_platform_administrator_view(request, user_id):
    config_error = _email_configuration_error()
    if config_error is not None:
        return config_error
    if not isinstance(request.data, dict) or set(request.data) != {"reason"}:
        return Response({"detail": "Provide a reason."}, status=400)
    reason = _reason_from(request.data)
    if reason is None:
        return Response({"detail": "Provide a reason of 8–500 characters."}, status=400)
    try:
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().filter(pk=user_id).first()
            if user is None:
                return Response({"detail": "Account not found."}, status=404)
            if user.is_superuser or not user.is_staff or user.pk == request.user.pk:
                return Response({"detail": "Protected administrator account."}, status=403)
            identity = PlatformAdminIdentity.objects.select_for_update().filter(user=user).first()
            if identity is None or identity.status == PlatformAdminIdentity.Status.ACTIVE:
                return Response({"detail": "Only invited or disabled administrators can be reinvited."}, status=409)
            # Changing the password marker revokes all previously issued links.
            user.is_active = False
            user.set_unusable_password()
            user.save(update_fields=["is_active", "password"])
            identity.status = PlatformAdminIdentity.Status.INVITED
            identity.activated_at = None
            identity.save(update_fields=["status", "activated_at"])
            _email_administrator_invitation(user)
            PlatformAdminAuditEvent.objects.create(
                actor=request.user, target_user=user,
                action=PlatformAdminAuditEvent.Action.INVITE_ADMIN,
                reason=reason, metadata={"delivery": "email", "resend": True},
            )
    except (SMTPException, OSError, ConnectionError):
        logger.warning("Administrator reinvitation delivery failed (no token logged).")
        return Response({"detail": "Could not deliver the invitation. Retry after checking email settings."}, status=503)
    return Response({"id": user_id, "status": "invited", "delivery": "email"})


@require_csrf
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def accept_platform_administrator_invitation_view(request):
    body = request.data
    if not isinstance(body, dict) or set(body) != {"uid", "token", "password1", "password2"}:
        return Response({"detail": "Invalid invitation request."}, status=400)
    uid, token, password1, password2 = (body.get(key) for key in ("uid", "token", "password1", "password2"))
    if any(not isinstance(item, str) for item in (uid, token, password1, password2)):
        return Response({"detail": "Invalid invitation request."}, status=400)
    if not uid or len(uid) > 128 or not token or len(token) > 256:
        return Response({"detail": "Invalid invitation link."}, status=400)
    if password1 != password2:
        return Response({"detail": "Passwords do not match."}, status=400)
    try:
        pk = force_str(urlsafe_base64_decode(uid))
        if not pk.isdecimal():
            raise ValueError("Invalid user ID")
    except (ValueError, TypeError, UnicodeDecodeError, OverflowError):
        return Response({"detail": "Invitation is invalid or expired."}, status=400)
    User = get_user_model()
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=pk).first()
        if user is None:
            return Response({"detail": "Invitation is invalid or expired."}, status=400)
        identity = PlatformAdminIdentity.objects.select_for_update().filter(user=user).first()
        if (identity is None or identity.status != PlatformAdminIdentity.Status.INVITED
                or user.is_active or not user.is_staff or user.is_superuser
                or user.has_usable_password()
                or not default_token_generator.check_token(user, token)):
            return Response({"detail": "Invitation is invalid or expired."}, status=400)
        try:
            validate_password(password1, user=user)
        except ValidationError as error:
            return Response({"detail": "Choose a stronger password.", "fieldErrors": {"password1": error.messages}}, status=400)
        user.set_password(password1)
        user.is_active = True
        user.save(update_fields=["password", "is_active"])
        identity.status = PlatformAdminIdentity.Status.ACTIVE
        identity.activated_at = timezone.now()
        identity.save(update_fields=["status", "activated_at"])
        PlatformAdminAuditEvent.objects.create(
            actor=user, target_user=user,
            action=PlatformAdminAuditEvent.Action.ACCEPT_ADMIN,
            reason="Administrator accepted a one-time invitation.",
        )
    return Response({"activated": True})


@require_csrf
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([SuperAdminOnly])
def disable_platform_administrator_view(request, user_id):
    if not isinstance(request.data, dict) or set(request.data) != {"reason"}:
        return Response({"detail": "Provide a reason."}, status=400)
    reason = _reason_from(request.data)
    if reason is None:
        return Response({"detail": "Provide a reason of 8–500 characters."}, status=400)
    if getattr(settings, "SESSION_ENGINE", "django.contrib.sessions.backends.db") != "django.contrib.sessions.backends.db":
        return Response({"detail": "Administrator session revocation requires Django database sessions."}, status=503)
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().filter(pk=user_id).first()
        if user is None:
            return Response({"detail": "Account not found."}, status=404)
        if user.pk == request.user.pk or user.is_superuser or not user.is_staff:
            return Response({"detail": "Protected administrator account."}, status=403)
        identity = PlatformAdminIdentity.objects.select_for_update().filter(user=user).first()
        if identity is None:
            return Response({"detail": "Not a dedicated administrator."}, status=403)
        if identity.status == PlatformAdminIdentity.Status.DISABLED:
            return Response({"detail": "Account is already disabled."}, status=409)
        identity.status = PlatformAdminIdentity.Status.DISABLED
        identity.save(update_fields=["status"])
        user.is_active = False
        user.set_unusable_password()
        user.save(update_fields=["is_active", "password"])
        revoke_all_database_sessions(user)
        PlatformAdminAuditEvent.objects.create(
            actor=request.user, target_user=user,
            action=PlatformAdminAuditEvent.Action.DISABLE_ADMIN,
            reason=reason,
        )
    return Response({"id": user.pk, "status": "disabled"})
