"""Provisioning dùng fixture PostgreSQL riêng; không đọc credentials hoặc tài khoản phục vụ."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import re
import secrets
from smtplib import SMTPException
from threading import Event
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Membership, OrganizationIdentity, PlatformAdminIdentity, QuotaAccount, QuotaAuditEvent, Tenant, Workspace
from logs.models import ActivityLog


@override_settings(DEBUG=True, ADMIN_INVITES_ENABLED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   NEXTJS_FRONTEND_URL='http://localhost:3000', DEFAULT_FROM_EMAIL='invitations@example.invalid')
class OrganizationProvisioningTests(TestCase):
    def setUp(self):
        self.operator = get_user_model().objects.create_superuser(
            username='operator-fixture', email='operator@example.invalid', password=secrets.token_urlsafe(32))
        self.client = self.as_user(self.operator)
        self.body = {'name': 'Example Organization', 'slug': 'example-organization',
                     'admin': {'username': 'organization-owner', 'email': 'owner@example.invalid'},
                     'limit_bytes': 4096, 'member_limit_bytes': 1024, 'reason': 'Approved organization onboarding'}
        self.key = str(uuid4())
        self.create_url = reverse('api-admin-organizations')

    def as_user(self, user=None):
        client = APIClient(enforce_csrf_checks=True)
        if user:
            client.force_login(user)
        return client

    def post(self, url, body, *, client=None, key=None, csrf=True):
        client = client or self.client
        headers = {'HTTP_IDEMPOTENCY_KEY': key or str(uuid4())}
        if csrf:
            bootstrap = client.get(reverse('api-csrf'))
            headers['HTTP_X_CSRFTOKEN'] = bootstrap.data['csrfToken']
        return client.post(url, body, format='json', **headers)

    def create(self, body=None, key=None):
        response = self.post(self.create_url, body or self.body, key=key or self.key)
        self.assertEqual(response.status_code, 201)
        return response

    def activation_payload(self):
        links = re.findall(r'https?://[^\s]+', mail.outbox[-1].body)
        self.assertEqual(len(links), 1)
        parts = urlsplit(links[0])
        self.assertEqual(parts.path, '/organization-invite')
        self.assertFalse(bool(parts.query))
        fields = parse_qs(parts.fragment)
        self.assertTrue(set(fields) == {'uid', 'token'})
        password = secrets.token_urlsafe(40)
        return {'uid': fields['uid'][0], 'token': fields['token'][0], 'password1': password, 'password2': password}

    def activate(self, payload=None):
        response = self.post(reverse('api-organization-invite-accept'), payload or self.activation_payload(),
                             client=self.as_user())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'activated': True})

    def owner_context(self):
        result = self.create()
        self.activate()
        tenant = Tenant.objects.get(pk=result.data['organization']['id'])
        owner = get_user_model().objects.get(pk=result.data['member']['userId'])
        return tenant, owner, self.as_user(owner)

    def employee_body(self):
        return {'username': 'employee-fixture', 'email': 'employee@example.invalid',
                'limit_bytes': 1024, 'reason': 'Approved employee onboarding'}

    def test_platform_creates_finite_managed_organization_without_personal_or_storage(self):
        result = self.create()
        user = get_user_model().objects.get(pk=result.data['member']['userId'])
        tenant = Tenant.objects.get(pk=result.data['organization']['id'])
        member = Membership.objects.get(tenant=tenant, user=user)
        self.assertFalse(user.is_active or user.is_staff or user.is_superuser or user.has_usable_password())
        self.assertEqual((member.role, member.status), (Membership.Role.OWNER, Membership.Status.INVITED))
        self.assertFalse(Tenant.objects.filter(personal_owner=user).exists())
        self.assertEqual(user.organization_identity.tenant_id, tenant.pk)
        drive = Workspace.objects.get(pk=result.data['myDrive']['workspaceId'])
        self.assertEqual(drive.owned_identity_id, user.pk)
        self.assertEqual(drive.tenant_id, tenant.pk)
        self.assertFalse(drive.is_default)
        self.assertEqual(result.data['myDrive']['ownership'], 'organization')
        self.assertFalse(result.data['storageReady'])
        self.assertFalse(tenant.storage_bindings.exists())
        self.assertFalse(QuotaAccount.objects.filter(workspace=drive).exists())
        quotas = QuotaAccount.objects.filter(tenant=tenant)
        self.assertEqual(quotas.count(), 2)
        self.assertEqual(set(quotas.values_list('limit_bytes', flat=True)), {1024, 4096})
        self.assertFalse(quotas.exclude(plan=None).exists())
        self.assertEqual(QuotaAuditEvent.objects.filter(quota_account__tenant=tenant).count(), 2)
        self.assertEqual(ActivityLog.objects.filter(tenant=tenant, action=ActivityLog.Action.CREATE_ORGANIZATION).count(), 1)
        self.assertTrue(result.data['organization']['pendingAdministratorInvitation'])
        self.assertEqual(result.data['organization']['workspaces'], 0)
        self.assertFalse(any(key in result.data for key in ('token', 'password', 'inviteToken')))
        self.assertEqual(len(mail.outbox), 1)

    def test_idempotency_replays_without_second_user_mail_or_quota_and_conflicts_fail(self):
        first = self.create()
        before = (get_user_model().objects.count(), QuotaAccount.objects.count(), ActivityLog.objects.count())
        again = self.post(self.create_url, self.body, key=self.key)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(first.data['organization']['id'], again.data['organization']['id'])
        self.assertEqual(first.data['member']['userId'], again.data['member']['userId'])
        self.assertEqual(before, (get_user_model().objects.count(), QuotaAccount.objects.count(), ActivityLog.objects.count()))
        self.assertEqual(len(mail.outbox), 1)
        changed = {**self.body, 'name': 'Different request'}
        self.assertEqual(self.post(self.create_url, changed, key=self.key).status_code, 409)
        self.operator.is_active = False
        self.operator.save(update_fields=['is_active'])
        self.assertIn(self.post(self.create_url, self.body, key=self.key).status_code, (401, 403))

    def test_never_promotes_or_attaches_existing_user(self):
        user = get_user_model().objects.create_user(username='existing-person', email='owner@example.invalid',
                                                     password=secrets.token_urlsafe(32))
        previous = user.password
        self.assertEqual(self.post(self.create_url, self.body).status_code, 409)
        user.refresh_from_db()
        self.assertTrue(user.password == previous)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(Tenant.objects.filter(personal_owner=user).exists())
        self.assertFalse(OrganizationIdentity.objects.filter(user=user).exists())
        self.assertFalse(Tenant.objects.filter(kind=Tenant.Kind.BUSINESS).exists())
        normalized_duplicate = deepcopy(self.body)
        normalized_duplicate['admin'] = {'username': 'ｅｘｉｓｔｉｎｇ-ｐｅｒｓｏｎ', 'email': 'new@example.invalid'}
        self.assertEqual(self.post(self.create_url, normalized_duplicate).status_code, 409)
        self.assertFalse(OrganizationIdentity.objects.filter(user=user).exists())

    def test_csrf_anonymous_regular_user_and_missing_idempotency_are_denied(self):
        self.assertEqual(self.post(self.create_url, self.body, csrf=False).status_code, 403)
        self.assertIn(self.post(self.create_url, self.body, client=self.as_user()).status_code, (401, 403))
        regular = get_user_model().objects.create_user(username='regular-fixture', password=secrets.token_urlsafe(32))
        self.assertEqual(self.post(self.create_url, self.body, client=self.as_user(regular)).status_code, 403)
        csrf = self.client.get(reverse('api-csrf')).data['csrfToken']
        missing = self.client.post(self.create_url, self.body, format='json', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(missing.status_code, 400)
        self.assertFalse(Tenant.objects.filter(kind=Tenant.Kind.BUSINESS).exists())

    def test_strict_finite_limits_and_identity_fields(self):
        for value in (None, True, -1, 10 ** 17 + 1):
            with self.subTest(limit=value):
                response = self.post(self.create_url, {**self.body, 'limit_bytes': value})
                self.assertEqual(response.status_code, 400)
                self.assertTrue(isinstance(response.data['fieldErrors']['limit_bytes'], list))
        self.assertEqual(self.post(self.create_url, {**self.body, 'member_limit_bytes': 4097}).status_code, 400)
        wrong = deepcopy(self.body)
        wrong['admin']['is_staff'] = True
        self.assertEqual(self.post(self.create_url, wrong).status_code, 400)
        self.assertEqual(self.post(self.create_url, {**self.body, 'role': 'super_admin'}).status_code, 400)
        self.assertFalse(OrganizationIdentity.objects.exists())

    def test_delivery_failure_rolls_back_all_new_identity_quota_and_audit(self):
        count = get_user_model().objects.count()
        with patch('accounts.organization_provisioning.send_mail', side_effect=SMTPException):
            response = self.post(self.create_url, self.body)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(get_user_model().objects.count(), count)
        self.assertFalse(OrganizationIdentity.objects.exists())
        self.assertFalse(Tenant.objects.filter(kind=Tenant.Kind.BUSINESS).exists())
        self.assertFalse(QuotaAuditEvent.objects.exists())
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.Action.CREATE_ORGANIZATION).exists())

    def test_audit_failure_sends_no_invitation_and_rolls_back_new_resources(self):
        create_log = ActivityLog.objects.create
        before = get_user_model().objects.count()

        def fail_organization_audit(**fields):
            if fields.get('action') == ActivityLog.Action.CREATE_ORGANIZATION:
                raise RuntimeError('Fixture audit write failure')
            return create_log(**fields)

        with patch('accounts.organization_provisioning.ActivityLog.objects.create', side_effect=fail_organization_audit), \
                patch('accounts.organization_provisioning.send_mail') as send:
            with self.assertRaises(RuntimeError):
                self.post(self.create_url, self.body)
        send.assert_not_called()
        self.assertEqual(get_user_model().objects.count(), before)
        self.assertFalse(OrganizationIdentity.objects.exists())
        self.assertFalse(Tenant.objects.filter(kind=Tenant.Kind.BUSINESS).exists())
        self.assertFalse(QuotaAuditEvent.objects.exists())

    def test_activation_requires_csrf_pending_token_password_policy_and_is_one_time(self):
        result = self.create()
        body = self.activation_payload()
        public = self.as_user()
        route = reverse('api-organization-invite-accept')
        self.assertEqual(self.post(route, body, client=public, csrf=False).status_code, 403)
        self.assertEqual(self.post(route, {**body, 'token': 'invalid'}, client=public).status_code, 400)
        self.assertEqual(self.post(route, {**body, 'password1': '1', 'password2': '1'}, client=public).status_code, 400)
        self.activate(body)
        user = get_user_model().objects.get(pk=result.data['member']['userId'])
        self.assertTrue(user.is_active and user.has_usable_password())
        self.assertTrue(user.organization_identity.activated_at is not None)
        self.assertEqual(Membership.objects.get(user=user).status, Membership.Status.ACTIVE)
        self.assertFalse(Tenant.objects.filter(personal_owner=user).exists())
        self.assertEqual(self.post(route, body, client=public).status_code, 400)

    def test_pending_owner_reinvite_invalidates_old_link_and_never_resets_active_user(self):
        result = self.create()
        old = self.activation_payload()
        route = reverse('api-admin-organization-reinvite', args=[result.data['organization']['id']])
        self.assertEqual(self.post(route, {'reason': 'Invitation delivery retry'}).status_code, 200)
        newest = self.activation_payload()
        self.assertEqual(self.post(reverse('api-organization-invite-accept'), old, client=self.as_user()).status_code, 400)
        self.activate(newest)
        user = get_user_model().objects.get(pk=result.data['member']['userId'])
        saved = user.password
        self.assertEqual(self.post(route, {'reason': 'Another delivery retry'}).status_code, 409)
        user.refresh_from_db()
        self.assertTrue(user.password == saved)
        self.assertTrue(user.is_active)

    def test_employee_creation_idempotency_and_revoked_actor_cannot_replay(self):
        tenant, owner, client = self.owner_context()
        route = reverse('api-organization-members', args=[tenant.pk])
        body, key = self.employee_body(), str(uuid4())
        created = self.post(route, body, client=client, key=key)
        self.assertEqual(created.status_code, 201)
        member = Membership.objects.get(pk=created.data['member']['membershipId'])
        self.assertEqual((member.role, member.status), (Membership.Role.MEMBER, Membership.Status.INVITED))
        self.assertEqual(member.user.organization_identity.tenant_id, tenant.pk)
        self.assertFalse(Tenant.objects.filter(personal_owner=member.user).exists())
        self.assertFalse(created.data['storageReady'])
        self.assertEqual(self.post(route, body, client=client, key=key).status_code, 200)
        self.assertEqual(len(mail.outbox), 2)
        Membership.objects.filter(tenant=tenant, user=owner).update(status=Membership.Status.REVOKED)
        self.assertEqual(self.post(route, body, client=client, key=key).status_code, 404)
        self.assertEqual(OrganizationIdentity.objects.filter(tenant=tenant).count(), 2)

    def test_employee_scope_rbac_and_finite_budget(self):
        tenant, owner, client = self.owner_context()
        route = reverse('api-organization-members', args=[tenant.pk])
        foreign = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name='Another organization')
        self.assertEqual(self.post(reverse('api-organization-members', args=[foreign.pk]), self.employee_body(), client=client).status_code, 404)
        self.assertEqual(self.post(route, {**self.employee_body(), 'role': 'admin'}, client=client).status_code, 400)
        self.assertEqual(self.post(route, {**self.employee_body(), 'limit_bytes': 4097}, client=client).status_code, 400)
        QuotaAccount.objects.filter(tenant=tenant, scope=QuotaAccount.Scope.TENANT).update(limit_bytes=None)
        self.assertEqual(self.post(route, self.employee_body(), client=client).status_code, 400)
        self.assertEqual(OrganizationIdentity.objects.filter(tenant=tenant).count(), 1)

    def test_pending_employee_reinvite_scope_and_activation_denied_after_offboarding(self):
        tenant, owner, client = self.owner_context()
        created = self.post(reverse('api-organization-members', args=[tenant.pk]), self.employee_body(), client=client)
        self.assertEqual(created.status_code, 201)
        old = self.activation_payload()
        member = Membership.objects.get(pk=created.data['member']['membershipId'])
        route = reverse('api-organization-member-reinvite', args=[tenant.pk, member.pk])
        outsider = get_user_model().objects.create_user(username='outsider-fixture', password=secrets.token_urlsafe(32))
        self.assertEqual(self.post(route, {'reason': 'Retry pending invitation'}, client=self.as_user(outsider)).status_code, 404)
        self.assertEqual(self.post(route, {'reason': 'Retry pending invitation'}, client=client).status_code, 200)
        new = self.activation_payload()
        self.assertEqual(self.post(reverse('api-organization-invite-accept'), old, client=self.as_user()).status_code, 400)
        member.status = Membership.Status.REVOKED
        member.save(update_fields=['status', 'updated_at'])
        self.assertEqual(self.post(reverse('api-organization-invite-accept'), new, client=self.as_user()).status_code, 400)
        self.assertTrue(OrganizationIdentity.objects.filter(user=member.user, tenant=tenant).exists())
        self.assertTrue(Workspace.objects.filter(owned_identity_id=member.user_id).exists())

    def test_delivery_gate_stays_off_and_console_tokens_are_never_emitted(self):
        for changes in ({'ADMIN_INVITES_ENABLED': False}, {'EMAIL_BACKEND': 'django.core.mail.backends.console.EmailBackend'},
                        {'DEBUG': False}):
            with self.subTest(config=list(changes)):
                with override_settings(**changes):
                    response = self.post(self.create_url, self.body)
                    self.assertEqual(response.status_code, 503)
                    self.assertFalse(self.client.get(self.create_url).data['capabilities']['createOrganization'])
        self.assertFalse(OrganizationIdentity.objects.exists())

    def test_active_non_super_platform_admin_can_provision_but_org_member_cannot(self):
        user = get_user_model().objects.create_user(username='platform-fixture', is_staff=True,
                                                    password=secrets.token_urlsafe(32))
        PlatformAdminIdentity.objects.create(user=user, invited_by=self.operator,
                                             status=PlatformAdminIdentity.Status.ACTIVE)
        response = self.post(self.create_url, self.body, client=self.as_user(user))
        self.assertEqual(response.status_code, 201)
        self.activate()
        owner = get_user_model().objects.get(pk=response.data['member']['userId'])
        self.assertEqual(self.post(self.create_url, {**self.body, 'slug': 'another'}, client=self.as_user(owner)).status_code, 403)


@override_settings(DEBUG=True, ADMIN_INVITES_ENABLED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   NEXTJS_FRONTEND_URL='http://localhost:3000', DEFAULT_FROM_EMAIL='invitations@example.invalid')
class OrganizationProvisioningConcurrencyTests(TransactionTestCase):
    serialized_rollback = True

    def test_email_update_and_provisioning_serialize_without_actor_lock_deadlock(self):
        from accounts.account_email import lock_email_identity, update_user_email
        from accounts.organization_provisioning import _lock_new_account, create_organization, ProvisioningError

        password = secrets.token_urlsafe(32)
        actor = get_user_model().objects.create_superuser(
            username='concurrent-operator', email='before@example.invalid', password=password)
        email_locked, provisioning_started, release_update = Event(), Event(), Event()
        body = {'name': 'Concurrent organization', 'slug': 'concurrent-organization',
                'admin': {'username': 'concurrent-owner', 'email': 'destination@example.invalid'},
                'limit_bytes': 4096, 'member_limit_bytes': 1024, 'reason': 'Approved concurrent onboarding'}

        def update_lock(email):
            lock_email_identity(email)
            email_locked.set()
            if not release_update.wait(5):
                raise TimeoutError('Email update was not released.')

        def provisioning_lock(account):
            provisioning_started.set()
            _lock_new_account(account)

        def worker(operation):
            close_old_connections()
            try:
                # Chặn test treo nếu thứ tự lock bị đảo trở lại.
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                return operation(get_user_model().objects.get(pk=actor.pk))
            finally:
                connection.close()

        def provision(user):
            try:
                create_organization(user, body, str(uuid4()))
            except ProvisioningError as error:
                return error.status
            return 201

        with patch('accounts.account_email.lock_email_identity', side_effect=update_lock), \
                patch('accounts.organization_provisioning._lock_new_account', side_effect=provisioning_lock), \
                ThreadPoolExecutor(max_workers=2) as pool:
            update = pool.submit(worker, lambda user: update_user_email(user, 'destination@example.invalid', password))
            try:
                self.assertTrue(email_locked.wait(5))
                creation = pool.submit(worker, provision)
                self.assertTrue(provisioning_started.wait(5))
            finally:
                release_update.set()
            self.assertTrue(update.result(timeout=15))
            self.assertEqual(creation.result(timeout=15), 409)
        actor.refresh_from_db()
        self.assertEqual(actor.email, 'destination@example.invalid')
        self.assertFalse(OrganizationIdentity.objects.exists())
        self.assertFalse(Tenant.objects.filter(kind=Tenant.Kind.BUSINESS).exists())
