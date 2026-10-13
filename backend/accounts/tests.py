from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Membership, Tenant
from logs.models import ActivityLog


class AccountApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="member",
            email="member@example.test",
            password="not-a-real-production-password",
        )
        self.client = APIClient()

    def _create_business_member(self, *, username, role=Membership.Role.MEMBER):
        tenant = Tenant.objects.create(
            kind=Tenant.Kind.BUSINESS,
            name=f"{username} workspace",
        )
        user = get_user_model().objects.create_user(username=username)
        membership = Membership.objects.create(
            tenant=tenant,
            user=user,
            role=role,
            status=Membership.Status.ACTIVE,
        )
        return tenant, user, membership

    def test_current_account_requires_authentication(self):
        response = self.client.get(reverse("api-current-account"))

        self.assertIn(response.status_code, (401, 403))

    def test_current_account_derives_type_and_role_from_membership(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(reverse("api-current-account"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["profile"], {
            "username": "member",
            "email": "member@example.test",
        })
        self.assertEqual(response.data["account"]["type"], "individual")
        self.assertEqual(response.data["account"]["tenant"]["role"], "owner")
        self.assertIsNone(response.data["account"]["upgradeEligible"])
        self.assertEqual(response.data["memberships"][0]["type"], "personal")

    def test_current_account_returns_business_membership_from_backend(self):
        tenant = Tenant.objects.create(
            kind=Tenant.Kind.BUSINESS,
            name="Example Business",
        )
        Membership.objects.create(
            tenant=tenant,
            user=self.user,
            role=Membership.Role.ADMIN,
            status=Membership.Status.ACTIVE,
        )
        self.client.force_authenticate(self.user)

        response = self.client.get(reverse("api-current-account"))

        self.assertEqual(response.data["account"]["type"], "business")
        self.assertEqual(response.data["account"]["tenant"]["id"], str(tenant.pk))
        self.assertEqual(response.data["account"]["tenant"]["role"], "admin")
        self.assertFalse(response.data["account"]["upgradeEligible"])

    def test_tenant_admin_can_suspend_and_restore_only_members_with_audit(self):
        tenant = Tenant.objects.create(
            kind=Tenant.Kind.BUSINESS,
            name="Admin workspace",
        )
        Membership.objects.create(
            tenant=tenant,
            user=self.user,
            role=Membership.Role.ADMIN,
            status=Membership.Status.ACTIVE,
        )
        member = get_user_model().objects.create_user(
            username="managed-member"
        )
        membership = Membership.objects.create(
            tenant=tenant,
            user=member,
            role=Membership.Role.MEMBER,
            status=Membership.Status.ACTIVE,
        )
        self.client.force_authenticate(self.user)

        suspended = self.client.post(
            reverse(
                "api-suspend-tenant-member",
                args=[tenant.pk, membership.pk],
            )
        )

        self.assertEqual(suspended.status_code, 200, suspended.data)
        membership.refresh_from_db()
        self.assertEqual(membership.status, Membership.Status.SUSPENDED)
        self.assertFalse(
            Membership.objects.filter(
                tenant=tenant,
                user=member,
                status=Membership.Status.ACTIVE,
            ).exists()
        )
        self.assertTrue(
            Membership.objects.filter(
                user=self.user,
                tenant=self.user.personal_tenant,
                status=Membership.Status.ACTIVE,
            ).exists()
        )
        self.assertTrue(
            ActivityLog.objects.filter(
                user=self.user,
                tenant=tenant,
                action=ActivityLog.Action.SUSPEND_MEMBER,
                metadata__membership_id=str(membership.pk),
            ).exists()
        )

        restored = self.client.post(
            reverse(
                "api-restore-tenant-member",
                args=[tenant.pk, membership.pk],
            )
        )

        self.assertEqual(restored.status_code, 200)
        membership.refresh_from_db()
        self.assertEqual(membership.status, Membership.Status.ACTIVE)
        self.assertTrue(
            ActivityLog.objects.filter(
                user=self.user,
                tenant=tenant,
                action=ActivityLog.Action.RESTORE_MEMBER,
                metadata__membership_id=str(membership.pk),
            ).exists()
        )

    def test_tenant_admin_cannot_suspend_admin_or_member_of_another_tenant(self):
        tenant = Tenant.objects.create(
            kind=Tenant.Kind.BUSINESS,
            name="Admin workspace",
        )
        Membership.objects.create(
            tenant=tenant,
            user=self.user,
            role=Membership.Role.ADMIN,
            status=Membership.Status.ACTIVE,
        )
        peer_admin = get_user_model().objects.create_user(
            username="peer-admin"
        )
        admin_membership = Membership.objects.create(
            tenant=tenant,
            user=peer_admin,
            role=Membership.Role.ADMIN,
            status=Membership.Status.ACTIVE,
        )
        other_tenant, _, other_membership = self._create_business_member(
            username="other-tenant-member"
        )
        self.client.force_authenticate(self.user)

        forbidden_role = self.client.post(
            reverse(
                "api-suspend-tenant-member",
                args=[tenant.pk, admin_membership.pk],
            )
        )
        hidden_tenant = self.client.post(
            reverse(
                "api-suspend-tenant-member",
                args=[tenant.pk, other_membership.pk],
            )
        )

        self.assertEqual(forbidden_role.status_code, 403)
        self.assertEqual(hidden_tenant.status_code, 404)
        self.assertNotEqual(other_tenant.pk, tenant.pk)
        self.assertFalse(
            ActivityLog.objects.filter(
                action=ActivityLog.Action.SUSPEND_MEMBER,
            ).exists()
        )

    def test_business_member_cannot_suspend_another_member(self):
        tenant = Tenant.objects.create(
            kind=Tenant.Kind.BUSINESS,
            name="Member workspace",
        )
        member = get_user_model().objects.create_user(
            username="ordinary-member"
        )
        Membership.objects.create(
            tenant=tenant,
            user=member,
            role=Membership.Role.MEMBER,
            status=Membership.Status.ACTIVE,
        )
        target = get_user_model().objects.create_user(
            username="another-member"
        )
        target_membership = Membership.objects.create(
            tenant=tenant,
            user=target,
            role=Membership.Role.MEMBER,
            status=Membership.Status.ACTIVE,
        )
        self.client.force_authenticate(member)

        response = self.client.post(
            reverse(
                "api-suspend-tenant-member",
                args=[tenant.pk, target_membership.pk],
            )
        )

        self.assertEqual(response.status_code, 404)
        target_membership.refresh_from_db()
        self.assertEqual(target_membership.status, Membership.Status.ACTIVE)

    def test_profile_patch_updates_only_valid_email(self):
        self.client.force_authenticate(self.user)

        invalid = self.client.patch(
            reverse("api-current-account"),
            {"email": "not-an-email"},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "member@example.test")

        unexpected_field = self.client.patch(
            reverse("api-current-account"),
            {"email": "new@example.test", "username": "attacker-change"},
            format="json",
        )
        self.assertEqual(unexpected_field.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "member@example.test")
        self.assertEqual(self.user.username, "member")

        valid = self.client.patch(
            reverse("api-current-account"),
            {"email": "new@example.test"},
            format="json",
        )
        self.assertEqual(valid.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.test")
        self.assertEqual(self.user.username, "member")

    def test_logout_api_invalidates_session(self):
        self.assertTrue(self.client.login(username="member", password="not-a-real-production-password"))

        response = self.client.post(reverse("api-logout"))

        self.assertEqual(response.status_code, 204)
        account_response = self.client.get(reverse("api-current-account"))
        self.assertIn(account_response.status_code, (401, 403))

    def test_registration_creates_account_without_revealing_existence(self):
        response = self.client.post(
            reverse("api-register"),
            {
                "username": "new-member",
                "email": "new-member@example.test",
                "password1": "The-Very-Long-Passphrase-93!",
                "password2": "The-Very-Long-Passphrase-93!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.data["detail"],
            "If registration can be completed, you can sign in to continue. "
            "If you cannot sign in, check your details or contact support.",
        )
        self.assertTrue(
            get_user_model().objects.filter(email="new-member@example.test").exists()
        )
        account_response = self.client.get(reverse("api-current-account"))
        self.assertIn(account_response.status_code, (401, 403))

    def test_logout_requires_csrf_and_invalidates_session(self):
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        denied = csrf_client.post(reverse("api-logout"))
        self.assertEqual(denied.status_code, 403)
        csrf_response = csrf_client.get(reverse("api-csrf"))
        response = csrf_client.post(
            reverse("api-logout"),
            HTTP_X_CSRFTOKEN=csrf_response.data["csrfToken"],
        )

        self.assertEqual(response.status_code, 204)
        account_response = csrf_client.get(reverse("api-current-account"))
        self.assertIn(account_response.status_code, (401, 403))

    def test_registration_validation_returns_field_errors(self):
        response = self.client.post(
            reverse("api-register"),
            {
                "username": "new-member",
                "email": "not-an-email",
                "password1": "The-Very-Long-Passphrase-93!",
                "password2": "a-different-passphrase",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data["fieldErrors"])
        self.assertIn("password2", response.data["fieldErrors"])
        self.assertFalse(get_user_model().objects.filter(username="new-member").exists())

    def test_registration_conflicts_do_not_reveal_existing_username_or_email(self):
        successful_registration = self.client.post(
            reverse("api-register"),
            {
                "username": "unique-registration",
                "email": "unique-registration@example.test",
                "password1": "The-Very-Long-Passphrase-93!",
                "password2": "The-Very-Long-Passphrase-93!",
            },
            format="json",
        )
        duplicate_email = self.client.post(
            reverse("api-register"),
            {
                "username": "different-member",
                "email": self.user.email,
                "password1": "The-Very-Long-Passphrase-93!",
                "password2": "The-Very-Long-Passphrase-93!",
            },
            format="json",
        )
        duplicate_username = self.client.post(
            reverse("api-register"),
            {
                "username": self.user.username,
                "email": "different@example.test",
                "password1": "The-Very-Long-Passphrase-93!",
                "password2": "The-Very-Long-Passphrase-93!",
            },
            format="json",
        )

        self.assertEqual(successful_registration.status_code, 202)
        self.assertEqual(duplicate_email.status_code, 202)
        self.assertEqual(duplicate_username.status_code, 202)
        self.assertEqual(successful_registration.data, duplicate_email.data)
        self.assertEqual(duplicate_email.data, duplicate_username.data)

    def test_login_rejects_invalid_credentials_without_user_enumeration(self):
        existing_email = self.client.post(
            reverse("api-login"),
            {"email": self.user.email, "password": "incorrect"},
            format="json",
        )
        unknown_email = self.client.post(
            reverse("api-login"),
            {"email": "unknown@example.test", "password": "incorrect"},
            format="json",
        )

        self.assertEqual(existing_email.status_code, 401)
        self.assertEqual(unknown_email.status_code, 401)
        self.assertEqual(existing_email.data, unknown_email.data)

    def test_login_authenticates_by_email_and_sets_session(self):
        login_user = get_user_model().objects.create_user(
            username="api-login-member",
            email="api-login@example.test",
            password="Test-Login-Password-742!",
        )
        response = self.client.post(
            reverse("api-login"),
            {"email": login_user.email, "password": "Test-Login-Password-742!"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["authenticated"])
        self.assertEqual(
            self.client.get(reverse("api-current-account")).status_code,
            200,
        )

    def test_expired_session_cannot_access_current_account(self):
        self.client.force_login(self.user)
        self.client.session.flush()

        response = self.client.get(reverse("api-current-account"))

        self.assertIn(response.status_code, (401, 403))

    def test_registration_requires_csrf_token(self):
        csrf_client = APIClient(enforce_csrf_checks=True)
        payload = {
            "username": "csrf-member",
            "email": "csrf-member@example.test",
            "password1": "The-Very-Long-Passphrase-93!",
            "password2": "The-Very-Long-Passphrase-93!",
        }

        denied = csrf_client.post(reverse("api-register"), payload, format="json")
        self.assertEqual(denied.status_code, 403)
        denied_login = csrf_client.post(
            reverse("api-login"),
            {"email": payload["email"], "password": payload["password1"]},
            format="json",
        )
        self.assertEqual(denied_login.status_code, 403)

        csrf_response = csrf_client.get(reverse("api-csrf"))
        allowed = csrf_client.post(
            reverse("api-register"),
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_response.data["csrfToken"],
        )
        self.assertEqual(allowed.status_code, 202)

    def test_server_rendered_logout_requires_post(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("logout"))

        self.assertEqual(response.status_code, 405)
        self.assertTrue("_auth_user_id" in self.client.session)

    @override_settings(NEXTJS_FRONTEND_URL="http://127.0.0.1:3000")
    def test_legacy_auth_pages_redirect_to_nextjs(self):
        login_response = self.client.get(reverse("login"))
        register_response = self.client.get(reverse("register"))

        self.assertRedirects(
            login_response,
            "http://127.0.0.1:3000/login",
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            register_response,
            "http://127.0.0.1:3000/register",
            fetch_redirect_response=False,
        )

    @override_settings(NEXTJS_FRONTEND_URL="https://app.example.test")
    def test_legacy_login_redirect_preserves_only_safe_next_path(self):
        safe_response = self.client.get(
            reverse("login"),
            {"next": "/drive/recent?sort=name"},
        )
        unsafe_response = self.client.get(
            reverse("login"),
            {"next": "https://attacker.example/"},
        )

        self.assertEqual(
            safe_response["Location"],
            "https://app.example.test/login?"
            "next=%2Fdrive%2Frecent%3Fsort%3Dname",
        )
        self.assertEqual(unsafe_response["Location"], "https://app.example.test/login")

    @override_settings(NEXTJS_FRONTEND_URL="http://127.0.0.1:3000")
    def test_legacy_login_post_does_not_authenticate_or_process_credentials(self):
        response = self.client.post(
            reverse("login"),
            {"username": "member", "password": "incorrect"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "http://127.0.0.1:3000/login")
        self.assertNotIn("_auth_user_id", self.client.session)
