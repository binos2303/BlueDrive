"""Tạo identity mới thuộc Organization; không nhận tài khoản có sẵn hoặc đổi storage."""
import hashlib
import json
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_slug
from django.db import transaction
from django.db.models import F, Q
from django.forms import EmailField
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.debug import sensitive_variables

from .access import active_membership
from .account_email import lock_email_identity
from .models import Membership, OrganizationIdentity, QuotaAccount, QuotaAuditEvent, Tenant, Workspace
from .platform_admin import is_platform_admin
from .quota_admin_api import MAX_BYTES
from .services import provision_organization_drive
from logs.models import ActivityLog


class ProvisioningError(Exception):
    def __init__(self, detail, *, status=400, fields=None):
        self.detail, self.status, self.fields = detail, status, fields or {}
        super().__init__(detail)


def _invalid(field, message):
    raise ProvisioningError(message, fields={field: [message]})


def invitation_available():
    from .platform_admin_provisioning import _email_configuration_error
    # Không đưa activation token ra console/file kể cả ở môi trường development.
    blocked = {'django.core.mail.backends.console.EmailBackend',
               'django.core.mail.backends.filebased.EmailBackend',
               'django.core.mail.backends.dummy.EmailBackend'}
    return settings.EMAIL_BACKEND not in blocked and _email_configuration_error() is None


def _require_delivery():
    if not invitation_available():
        raise ProvisioningError("Organization invitations are unavailable. Contact a platform operator.", status=503)


def _reason(body):
    reason = body.get('reason')
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 500:
        _invalid('reason', 'Provide a reason of 8–500 characters.')
    return reason.strip()


def _limit(value, field):
    if type(value) is not int or not 0 <= value <= MAX_BYTES:
        _invalid(field, 'Provide a finite nonnegative storage limit.')
    return value


def _account(body, prefix=''):
    if not isinstance(body, dict) or set(body) != {'username', 'email'}:
        _invalid(prefix + 'username', 'Provide only username and email.')
    username, email = body['username'], body['email']
    if not isinstance(username, str):
        _invalid(prefix + 'username', 'Username must contain 3–150 characters.')
    username = get_user_model().normalize_username(username.strip())
    if not 3 <= len(username) <= get_user_model()._meta.get_field('username').max_length:
        _invalid(prefix + 'username', 'Username must contain 3–150 characters.')
    try:
        UnicodeUsernameValidator()(username)
    except ValidationError:
        _invalid(prefix + 'username', 'Provide a valid username.')
    if not isinstance(email, str):
        _invalid(prefix + 'email', 'Provide a valid email address.')
    try:
        email = EmailField(max_length=254).clean(email.strip().lower())
    except ValidationError:
        _invalid(prefix + 'email', 'Provide a valid email address.')
    return {'username': username, 'email': email}


def _key(value):
    try:
        return UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _request_key(value):
    key = _key(value)
    if key is None:
        _invalid('idempotencyKey', 'Provide a UUID Idempotency-Key header.')
    return key


def _digest(actor, operation, body, tenant_id=None):
    data = {'actor': actor.pk, 'operation': operation, 'tenant': str(tenant_id or ''), 'body': body}
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _platform_actor(actor):
    user = get_user_model().objects.select_for_update().filter(pk=actor.pk).first()
    if not is_platform_admin(user):
        raise ProvisioningError('Platform administrator access is required.', status=403)
    return user


def _organization_actor(actor, tenant_id):
    tenant = Tenant.objects.select_for_update().filter(pk=tenant_id, kind=Tenant.Kind.BUSINESS, status=Tenant.Status.ACTIVE).first()
    if tenant is None:
        raise ProvisioningError('Organization is unavailable.', status=404)
    member = Membership.objects.select_for_update().filter(tenant=tenant, user_id=actor.pk, status=Membership.Status.ACTIVE).first()
    if member is None:
        raise ProvisioningError('Organization access is unavailable.', status=404)
    user = get_user_model().objects.select_for_update().filter(pk=actor.pk).first()
    if is_platform_admin(user) or active_membership(user, tenant.pk) is None:
        raise ProvisioningError('Organization access is unavailable.', status=404)
    if member.role not in (Membership.Role.OWNER, Membership.Role.ADMIN):
        raise ProvisioningError('Organization administrator access is required.', status=403)
    return user, tenant


def member_capabilities(actor, tenant):
    member = active_membership(actor, tenant.pk)
    allowed = bool(tenant.kind == Tenant.Kind.BUSINESS and tenant.status == Tenant.Status.ACTIVE
                   and not is_platform_admin(actor) and member
                   and member.role in (Membership.Role.OWNER, Membership.Role.ADMIN))
    return {'inviteAccounts': allowed and invitation_available(), 'manageAccounts': allowed}


def member_data(member):
    identity = drive = None
    try:
        identity = member.user.organization_identity
        if identity.tenant_id == member.tenant_id:
            drive = identity.my_drive
    except ObjectDoesNotExist:
        pass
    managed = bool(identity and identity.tenant_id == member.tenant_id)
    return {'membershipId': str(member.pk), 'userId': member.user_id,
            'username': member.user.get_username(), 'email': member.user.email,
            'role': member.role, 'status': member.status, 'managed': managed,
            'myDriveWorkspaceId': str(drive.pk) if drive else None}


def organization_row(tenant):
    count = getattr(tenant, 'workspace_count', None)
    if count is None:
        count = Workspace.objects.filter(tenant=tenant, is_default=False, owned_identity__isnull=True,
                                         status=Workspace.Status.ACTIVE).count() if tenant.status == Tenant.Status.ACTIVE else 0
    pending = Membership.objects.filter(tenant=tenant, role=Membership.Role.OWNER, status=Membership.Status.INVITED,
                                         user__is_active=False, user__organization_identity__tenant=tenant,
                                         user__organization_identity__activated_at__isnull=True).exists()
    return {'id': str(tenant.pk), 'name': tenant.name, 'status': tenant.status,
            'workspaces': count, 'created_at': tenant.created_at.isoformat(),
            'pendingAdministratorInvitation': pending}


def _storage_ready(tenant, drive):
    if not settings.SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED or tenant.status != Tenant.Status.ACTIVE:
        return False
    from infrastructure.models import StorageBinding
    return StorageBinding.objects.filter(
        tenant=tenant, state='active', cluster__kind='enterprise', cluster__tenant=tenant, cluster__state='ready',
        storage_config__tenant=tenant, storage_config__status='active', connection__state='ready',
        connection__verified_at__isnull=False, connection__last_error_code='',
        connection__cluster__kind='enterprise', connection__cluster__tenant=tenant,
        connection__cluster__state='ready', connection__cluster_id=F('cluster_id'),
    ).filter(Q(scope='tenant', workspace__isnull=True) | Q(scope='workspace', workspace=drive)).exists()


def _response(tenant, member, *, organization=False):
    drive = member.user.organization_identity.my_drive
    result = {'member': member_data(member), 'myDrive': {'tenantId': str(tenant.pk), 'workspaceId': str(drive.pk),
                                                        'ownership': 'organization'},
              'storageReady': _storage_ready(tenant, drive)}
    if organization:
        result['organization'] = organization_row(tenant)
    return result


def _lock_new_account(account):
    lock_email_identity(account['email'])
    # Username namespace không thể trùng email hợp lệ; serialize các đường provision P2.
    lock_email_identity('organization-username:' + account['username'].casefold())


def _check_new_account(account):
    users = get_user_model().objects
    if users.filter(username__iexact=account['username']).exists() or users.filter(email__iexact=account['email']).exists():
        raise ProvisioningError('The username or email is already registered. Use a new organization identity.', status=409)


def _quota(actor, tenant, user, limit, reason):
    row = QuotaAccount.objects.create(tenant=tenant, user=user,
                                      scope=QuotaAccount.Scope.MEMBER if user else QuotaAccount.Scope.TENANT,
                                      limit_bytes=limit, plan=None)
    QuotaAuditEvent.objects.create(actor=actor, quota_account=row, old_limit_bytes=0,
                                   new_limit_bytes=limit, old_plan_code='', new_plan_code='', reason=reason)


@sensitive_variables('token', 'uid', 'link')
def _send_invitation(user):
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_str(user.pk).encode())
    link = f"{settings.NEXTJS_FRONTEND_URL}/organization-invite#{urlencode({'uid': uid, 'token': token})}"
    send_mail('Activate your BlueDrive Organization account',
              f'You have been invited to an Organization in BlueDrive.\n\nSet your password using this one-time link:\n{link}\n\nIf unexpected, ignore this message. The link expires automatically.',
              settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)


def _new_member(actor, tenant, account, role, key, digest, limit, reason):
    user = get_user_model()(**account, is_active=False, is_staff=False, is_superuser=False)
    user._skip_personal_tenant_provisioning = True
    user.set_unusable_password()
    user.save()
    identity = OrganizationIdentity.objects.create(user=user, tenant=tenant, invited_by=actor,
                                                    request_key=key, request_digest=digest)
    member = Membership.objects.create(tenant=tenant, user=user, role=role, status=Membership.Status.INVITED)
    try:
        provision_organization_drive(identity)
    except ValueError:
        raise ProvisioningError('Organization My Drive conflicts with an existing workspace.', status=409) from None
    _quota(actor, tenant, user, limit, reason)
    ActivityLog.objects.create(user=actor, tenant=tenant, action=ActivityLog.Action.INVITE_ORG_MEMBER,
                                description='Invited a new organization-managed account.',
                                metadata={'targetUserId': user.pk, 'membershipId': str(member.pk), 'role': role, 'reason': reason})
    return member


@transaction.atomic
def create_organization(actor, body, request_key):
    if not is_platform_admin(actor):
        raise ProvisioningError('Platform administrator access is required.', status=403)
    _require_delivery()
    expected = {'name', 'slug', 'admin', 'limit_bytes', 'member_limit_bytes', 'reason'}
    if not isinstance(body, dict) or set(body) != expected:
        raise ProvisioningError('Provide only name, slug, admin, limits and reason.')
    name, slug = body['name'], body['slug']
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 255:
        _invalid('name', 'Provide an organization name of 1–255 characters.')
    if not isinstance(slug, str) or not 1 <= len(slug.strip()) <= 100:
        _invalid('slug', 'Provide a valid organization slug.')
    slug = slug.strip().lower()
    try:
        validate_slug(slug)
    except ValidationError:
        _invalid('slug', 'Provide a valid organization slug.')
    account = _account(body['admin'], 'admin.')
    total = _limit(body['limit_bytes'], 'limit_bytes')
    limit = _limit(body['member_limit_bytes'], 'member_limit_bytes')
    if limit > total:
        _invalid('member_limit_bytes', 'Member allocation cannot exceed the organization limit.')
    reason = _reason(body)
    key = _request_key(request_key)
    normalized = {'name': name.strip(), 'slug': slug, 'admin': account, 'limit_bytes': total,
                  'member_limit_bytes': limit, 'reason': reason}
    digest = _digest(actor, 'organization.create', normalized)
    # Cùng thứ tự email lock → User với registration/email update để tránh deadlock.
    _lock_new_account(account)
    actor = _platform_actor(actor)
    existing = Tenant.objects.select_for_update().filter(provisioning_key=key).first()
    if existing:
        if existing.provisioning_digest != digest:
            raise ProvisioningError('Idempotency key was used for a different request.', status=409)
        member = Membership.objects.select_related('user').filter(tenant=existing,
                                                                  user__organization_identity__request_key=key).first()
        if member is None:
            raise ProvisioningError('Provisioned organization identity is unavailable.', status=409)
        return _response(existing, member, organization=True), True
    _check_new_account(account)
    if Tenant.objects.filter(slug__iexact=slug).exists():
        raise ProvisioningError('Organization slug is already registered.', status=409, fields={'slug': ['Organization slug is already registered.']})
    tenant = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name=name.strip(), slug=slug,
                                    provisioning_key=key, provisioning_digest=digest)
    _quota(actor, tenant, None, total, reason)
    member = _new_member(actor, tenant, account, Membership.Role.OWNER, key, digest, limit, reason)
    ActivityLog.objects.create(user=actor, tenant=tenant, action=ActivityLog.Action.CREATE_ORGANIZATION,
                                description='Created an organization with an invited initial administrator.',
                                metadata={'initialAdministratorId': member.user_id, 'reason': reason})
    result = _response(tenant, member, organization=True)
    # Hoàn tất mọi ghi DB trước khi gửi; không có token được gửi nếu audit thất bại.
    _send_invitation(member.user)
    return result, False


@transaction.atomic
def create_employee(actor, tenant_id, body, request_key):
    _require_delivery()
    if not isinstance(body, dict) or set(body) != {'username', 'email', 'limit_bytes', 'reason'}:
        raise ProvisioningError('Provide only username, email, limit_bytes and reason.')
    account = _account({key: body[key] for key in ('username', 'email')})
    limit = _limit(body['limit_bytes'], 'limit_bytes')
    reason, key = _reason(body), _request_key(request_key)
    _lock_new_account(account)
    actor, tenant = _organization_actor(actor, tenant_id)
    digest = _digest(actor, 'organization.employee.create', {**account, 'limit_bytes': limit, 'reason': reason}, tenant.pk)
    existing = OrganizationIdentity.objects.filter(request_key=key).first()
    if existing:
        if existing.tenant_id != tenant.pk or existing.request_digest != digest:
            raise ProvisioningError('Idempotency key was used for a different request.', status=409)
        member = Membership.objects.select_for_update(of=('self',)).select_related('user').filter(tenant=tenant, user_id=existing.user_id).first()
        if member is None:
            raise ProvisioningError('Provisioned member is unavailable.', status=409)
        return _response(tenant, member), True
    total = QuotaAccount.objects.select_for_update().filter(tenant=tenant, scope=QuotaAccount.Scope.TENANT).first()
    if total is None or total.limit_bytes is None or limit > total.limit_bytes:
        _invalid('limit_bytes', 'Member allocation requires a finite organization budget and cannot exceed it.')
    _check_new_account(account)
    member = _new_member(actor, tenant, account, Membership.Role.MEMBER, key, digest, limit, reason)
    result = _response(tenant, member)
    _send_invitation(member.user)
    return result, False


@transaction.atomic
def reinvite(actor, tenant_id, body, *, membership_id=None, initial_admin=False):
    if initial_admin:
        # Platform actor → Tenant giống create/replay Organization.
        actor = _platform_actor(actor)
        tenant = Tenant.objects.select_for_update().filter(pk=tenant_id, kind=Tenant.Kind.BUSINESS, status=Tenant.Status.ACTIVE).first()
        if tenant is None:
            raise ProvisioningError('Organization is unavailable.', status=404)
    else:
        actor, tenant = _organization_actor(actor, tenant_id)
    _require_delivery()
    if not isinstance(body, dict) or set(body) != {'reason'}:
        raise ProvisioningError('Provide only reason.')
    reason = _reason(body)
    members = Membership.objects.filter(tenant=tenant, role=Membership.Role.OWNER if initial_admin else Membership.Role.MEMBER)
    member = members.select_for_update(of=('self',)).filter(**({'user__organization_identity__tenant': tenant} if initial_admin else {'pk': membership_id})).first()
    if member is None:
        raise ProvisioningError('Organization member is unavailable.', status=404)
    identity = OrganizationIdentity.objects.select_for_update().filter(user_id=member.user_id, tenant=tenant).first()
    user = get_user_model().objects.select_for_update().get(pk=member.user_id)
    if (identity is None or identity.activated_at is not None or user.is_active or user.is_staff or user.is_superuser
            or user.has_usable_password() or member.status != Membership.Status.INVITED):
        raise ProvisioningError('Only pending organization-managed accounts can be reinvited.', status=409)
    user.set_unusable_password()
    user.save(update_fields=['password'])
    ActivityLog.objects.create(user=actor, tenant=tenant, action=ActivityLog.Action.INVITE_ORG_MEMBER,
                                description='Reissued a pending organization account invitation.',
                                metadata={'targetUserId': user.pk, 'reason': reason, 'resend': True})
    result = {'member': member_data(member), 'organizationId': str(tenant.pk), 'delivery': 'email'}
    _send_invitation(user)
    return result


@sensitive_variables('body', 'uid', 'token', 'first', 'second')
@transaction.atomic
def accept_invitation(body):
    if not isinstance(body, dict) or set(body) != {'uid', 'token', 'password1', 'password2'}:
        raise ProvisioningError('Invalid invitation request.')
    uid, token, first, second = (body[key] for key in ('uid', 'token', 'password1', 'password2'))
    if any(not isinstance(value, str) for value in (uid, token, first, second)) or not uid or len(uid) > 128 or not token or len(token) > 256:
        raise ProvisioningError('Invalid invitation request.')
    if first != second:
        _invalid('password2', 'Passwords do not match.')
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        if not user_id.isdecimal():
            raise ValueError
    except (ValueError, TypeError, UnicodeDecodeError, OverflowError):
        raise ProvisioningError('Invitation is invalid or expired.') from None
    initial = OrganizationIdentity.objects.filter(user_id=user_id).values('tenant_id').first()
    if initial is None:
        raise ProvisioningError('Invitation is invalid or expired.')
    tenant = Tenant.objects.select_for_update().filter(pk=initial['tenant_id'], kind=Tenant.Kind.BUSINESS, status=Tenant.Status.ACTIVE).first()
    member = Membership.objects.select_for_update().filter(tenant=tenant, user_id=user_id).first() if tenant else None
    identity = OrganizationIdentity.objects.select_for_update().filter(user_id=user_id, tenant=tenant).first() if member else None
    user = get_user_model().objects.select_for_update().filter(pk=user_id).first() if identity else None
    if (identity is None or member is None or member.status != Membership.Status.INVITED
            or identity.activated_at is not None or user.is_active or user.is_staff or user.is_superuser
            or user.has_usable_password() or not default_token_generator.check_token(user, token)):
        raise ProvisioningError('Invitation is invalid or expired.')
    try:
        validate_password(first, user=user)
    except ValidationError as error:
        raise ProvisioningError('Choose a stronger password.', fields={'password1': error.messages}) from None
    user.set_password(first)
    user.is_active = True
    user.save(update_fields=['password', 'is_active'])
    member.status = Membership.Status.ACTIVE
    member.save(update_fields=['status', 'updated_at'])
    identity.activated_at = timezone.now()
    identity.save(update_fields=['activated_at'])
    ActivityLog.objects.create(user=user, tenant=tenant, action=ActivityLog.Action.ACTIVATE_ORG_MEMBER,
                                description='Activated an organization-managed account using its invitation.')
    return {'activated': True}
