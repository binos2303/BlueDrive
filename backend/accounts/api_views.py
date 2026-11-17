from .platform_admin import is_platform_admin
from .access import active_membership
from django import forms
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from logs.models import ActivityLog
from logs.services import log_action

from .forms import RegisterForm
from .models import Membership, Tenant
from .views import ProfileEmailForm
from .account_email import EmailUpdateDenied, lock_email_identity, update_user_email
from django.shortcuts import get_object_or_404


def require_csrf(view):
    view.csrf_exempt = False
    protected_view = csrf_protect(view)
    protected_view.csrf_exempt = False
    return protected_view


@ensure_csrf_cookie
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def csrf_token_view(request):
    from django.middleware.csrf import get_token

    return Response({"csrfToken": get_token(request)})


def _registration_accepted():
    return Response(
        {
            "detail": (
                "If registration can be completed, you can sign in to continue. "
                "If you cannot sign in, check your details or contact support."
            )
        },
        status=status.HTTP_202_ACCEPTED,
    )


def _account_snapshot(user, request=None):
    """Snapshot dùng cùng context đã cấp quyền; My Drive luôn trỏ vùng home riêng."""
    from types import SimpleNamespace
    from .access import (ActiveTenantRequired, _request_workspace_values,
                         get_default_tenant, get_organization_identity, resolve_request_workspace)

    memberships = list(Membership.objects.filter(
        user=user, status=Membership.Status.ACTIVE, tenant__status=Tenant.Status.ACTIVE,
    ).select_related("tenant").order_by("tenant__kind", "tenant__name", "tenant_id"))
    identity = get_organization_identity(user)
    try:
        home_tenant = get_default_tenant(user)
    except ActiveTenantRequired:
        if identity is not None:
            raise
        home_tenant = None
    home_workspace = resolve_request_workspace(SimpleNamespace(user=user), home_tenant) if home_tenant else None
    if identity is not None and home_workspace is None:
        raise ActiveTenantRequired("Organization My Drive is unavailable.")
    selected_workspace = resolve_request_workspace(request) if request is not None else home_workspace
    if request is not None and _request_workspace_values(request) and selected_workspace is None:
        raise ActiveTenantRequired("Selected workspace is unavailable.")
    selected_tenant = selected_workspace.tenant if selected_workspace else home_tenant
    selected_membership = next((row for row in memberships if selected_tenant and row.tenant_id == selected_tenant.pk), None)
    account_type = ("business" if selected_tenant and selected_tenant.kind == Tenant.Kind.BUSINESS
                    else "individual" if selected_tenant and selected_tenant.kind == Tenant.Kind.PERSONAL
                    else "unclassified")
    return {
        "is_platform_admin": is_platform_admin(user),
        "profile": {"username": user.get_username(), "email": user.email},
        "account": {
            "type": account_type,
            "tenant": ({"id": str(selected_membership.tenant_id), "name": selected_membership.tenant.name,
                        "role": selected_membership.role} if selected_membership else None),
            "upgradeEligible": None if account_type == "individual" else False,
        },
        "myDrive": ({"tenantId": str(home_workspace.tenant_id), "workspaceId": str(home_workspace.pk),
                     "ownership": "organization" if identity is not None else "personal"} if home_workspace else None),
        "memberships": [{"id": str(row.tenant_id), "name": row.tenant.name,
                         "type": row.tenant.kind, "role": row.role} for row in memberships],
    }


@require_csrf
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def register_api_view(request):
    if not isinstance(request.data, dict):
        return Response(
            {"detail": "A JSON object is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    unexpected_fields = set(request.data) - {
        "username",
        "email",
        "password1",
        "password2",
    }
    if unexpected_fields:
        return Response(
            {"detail": "Unsupported registration fields."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    form = RegisterForm(request.data)
    if not form.is_valid():
        form_errors = form.errors.as_data()
        username_conflict = any(
            error.code == "unique"
            for error in form_errors.get("username", [])
        )
        field_errors = {
            field: [
                str(error.message)
                for error in errors
                if not (field == "username" and error.code == "unique")
            ]
            for field, errors in form_errors.items()
        }
        field_errors = {
            field: errors for field, errors in field_errors.items() if errors
        }
        if not field_errors and username_conflict:
            return _registration_accepted()
        return Response(
            {"detail": "Please correct the highlighted fields.",
             "fieldErrors": field_errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if get_user_model().objects.filter(
        email__iexact=form.cleaned_data["email"].strip()
    ).exists():
        return _registration_accepted()

    try:
        with transaction.atomic():
            lock_email_identity(form.cleaned_data["email"])
            if get_user_model().objects.filter(
                email__iexact=form.cleaned_data["email"]
            ).exists():
                return _registration_accepted()
            form.save()
    except IntegrityError:
        user_model = get_user_model()
        if (
            user_model.objects.filter(username=form.cleaned_data["username"]).exists()
            or user_model.objects.filter(
                email__iexact=form.cleaned_data["email"]
            ).exists()
        ):
            return _registration_accepted()
        raise

    return _registration_accepted()


@require_csrf
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def login_api_view(request):
    if not isinstance(request.data, dict):
        return Response(
            {"detail": "A JSON object is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    unexpected_fields = set(request.data) - {"email", "password"}
    if unexpected_fields:
        return Response(
            {"detail": "Unsupported login fields."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    email = request.data.get("email")
    password = request.data.get("password")
    field_errors = {}
    if not isinstance(email, str) or not email.strip():
        field_errors["email"] = ["Enter a valid email address."]
    else:
        try:
            email = forms.EmailField().clean(email.strip())
        except ValidationError as error:
            field_errors["email"] = [str(message) for message in error.messages]
    if not isinstance(password, str) or not password:
        field_errors["password"] = ["This field is required."]
    if field_errors:
        return Response(
            {
                "detail": "Please correct the highlighted fields.",
                "fieldErrors": field_errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    matching_users = list(
        get_user_model().objects.filter(email__iexact=email.strip()).order_by("pk")[:2]
    )
    if len(matching_users) != 1:
        authenticate(request, username=email, password=password)
        return Response(
            {"detail": "Invalid email or password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    user = authenticate(
        request,
        username=matching_users[0].get_username(),
        password=password,
    )
    if user is None:
        return Response(
            {"detail": "Invalid email or password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    login(request, user)
    log_action(user, ActivityLog.Action.LOGIN, "Successful login")
    return Response({"authenticated": True})


@api_view(["GET", "PATCH"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def current_account_view(request):
    if request.method == "GET":
        return Response(_account_snapshot(request.user, request))

    # Không ghi profile rồi mới phát hiện selector hoặc managed context không hợp lệ.
    _account_snapshot(request.user, request)

    if not isinstance(request.data, dict) or set(request.data) != {"email", "current_password"}:
        return Response({"detail": "Email and current password are required."}, status=400)

    form = ProfileEmailForm({"email": request.data.get("email", "")})
    if not form.is_valid():
        return Response(
            {"fieldErrors": form.errors.get_json_data()},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        update_user_email(request.user, form.cleaned_data["email"], request.data["current_password"])
    except EmailUpdateDenied as error:
        return Response({"detail": error.detail, "fieldErrors": {error.field: [error.detail]}}, status=error.status)
    return Response(_account_snapshot(request.user, request))


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def logout_api_view(request):
    user = request.user
    log_action(user, ActivityLog.Action.LOGOUT, "User logout")
    logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@require_csrf
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def suspend_tenant_member_view(request, tenant_id, membership_id):
    return _set_tenant_member_suspension(
        request,
        tenant_id=tenant_id,
        membership_id=membership_id,
        suspended=True,
    )


@require_csrf
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def restore_tenant_member_view(request, tenant_id, membership_id):
    return _set_tenant_member_suspension(
        request,
        tenant_id=tenant_id,
        membership_id=membership_id,
        suspended=False,
    )


def _set_tenant_member_suspension(
    request,
    *,
    tenant_id,
    membership_id,
    suspended,
):
    expected_status = (
        Membership.Status.ACTIVE
        if suspended
        else Membership.Status.SUSPENDED
    )
    new_status = (
        Membership.Status.SUSPENDED
        if suspended
        else Membership.Status.ACTIVE
    )
    action = (
        ActivityLog.Action.SUSPEND_MEMBER
        if suspended
        else ActivityLog.Action.RESTORE_MEMBER
    )
    description = (
        "Suspended tenant member"
        if suspended
        else "Restored tenant member"
    )

    with transaction.atomic():
        tenant = get_object_or_404(
            Tenant.objects.select_for_update(),
            pk=tenant_id,
            kind=Tenant.Kind.BUSINESS,
            status=Tenant.Status.ACTIVE,
        )
        actor_membership = (
            Membership.objects.select_for_update()
            .filter(
                tenant=tenant,
                user=request.user,
                status=Membership.Status.ACTIVE,
            )
            .first()
        )
        if (
            actor_membership is None
            or active_membership(request.user, tenant.pk) is None
            or actor_membership.role
            not in (Membership.Role.OWNER, Membership.Role.ADMIN)
        ):
            return Response(
                {"detail": "Tenant administrator access is required.",
                 "code": "tenant_admin_required"},
                status=status.HTTP_404_NOT_FOUND,
            )

        target = get_object_or_404(
            Membership.objects.select_for_update().select_related("user"),
            pk=membership_id,
            tenant=tenant,
        )
        if target.role != Membership.Role.MEMBER:
            return Response(
                {"detail": "Only tenant members can be changed by this endpoint.",
                 "code": "membership_role_not_allowed"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if target.status != expected_status:
            return Response(
                {"detail": "The membership is not in a state for this operation.",
                 "code": "membership_state_conflict"},
                status=status.HTTP_409_CONFLICT,
            )

        from .models import OrganizationIdentity
        identity = OrganizationIdentity.objects.select_for_update().filter(user_id=target.user_id, tenant=tenant).first()
        managed_user = get_user_model().objects.select_for_update().get(pk=target.user_id) if identity else None
        if managed_user is not None and not suspended and (identity.activated_at is None or not managed_user.has_usable_password()):
            return Response({"detail": "Accept the account invitation before restoring access.", "code": "invitation_required"}, status=409)
        target.status = new_status
        target.save(update_fields=["status", "updated_at"])
        if managed_user is not None:
            # Identity riêng của Organization: offboard chặn login, không xóa hồ sơ/data.
            managed_user.is_active = not suspended
            managed_user.save(update_fields=["is_active"])
        ActivityLog.objects.create(
            user=request.user,
            tenant=tenant,
            action=action,
            description=f"{description}: {target.user.get_username()}",
            metadata={
                "membership_id": str(target.pk),
                "target_user_id": target.user_id,
            },
        )

    return Response({
        "membership": {
            "id": str(target.pk),
            "userId": target.user_id,
            "role": target.role,
            "status": target.status,
        }
    })
