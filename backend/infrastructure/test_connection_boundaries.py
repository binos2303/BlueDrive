"""Ranh giới quyền, phục hồi cleanup và lease cho phép kiểm tra lại an toàn."""
import io
from datetime import timedelta
from unittest.mock import patch
from botocore.exceptions import SSLError, ReadTimeoutError

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from infrastructure.models import StorageAccessGrant, StorageConnectionProbe
from infrastructure.test_connections import WorkflowFixture


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True,SECUREDRIVE_STORAGE_LAB_PROBES_ENABLED=True)
class ConnectionBoundaryTests(WorkflowFixture, TestCase):
    def test_other_org_platform_and_viewer_cannot_control_connection(self):
        self.create_connection()
        self.read_check()
        self.start()
        for user in (self.other_owner,self.root,self.viewer):
            self.client.force_login(user)
            for suffix,body in (('verify/',{'reason':'Attempt cross-boundary action'}),('probe/',{'reason':'Attempt cross-boundary action','confirm_lab_fixture':True})):
                response = self.client.post(self.base+suffix,body,content_type='application/json')
                self.assertIn(response.status_code,(403,404))
            self.assertIn(self.client.post(self.probe_url+'cleanup/',{},content_type='application/json').status_code,(403,404))

    def test_other_org_profile_reference_is_not_accepted(self):
        self.profiles['org-b-v1'] = {**self.profiles['org-a-v1'],'tenant_id':str(self.other_tenant.pk)}
        result = self.connect({'display_name':'Cross target','slug':'cross-target','profile_id':'org-b-v1','reason':'Attempt cross-organization profile'})
        self.assertEqual(result.status_code,503)
        self.assertEqual(result.json()['code'],'profile_unavailable')
        self.assertEqual(self.remote.calls,[])

    def test_mutation_requires_csrf_even_with_real_session_cookie(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        result = browser.post(self.path('clusters/connect/'),{'display_name':'CSRF test','slug':'csrf-test','profile_id':'org-a-v1','reason':'Missing CSRF token test'},content_type='application/json',HTTP_IDEMPOTENCY_KEY='csrf-regression-key')
        self.assertEqual(result.status_code,403)

    def test_probe_digest_does_not_allow_expired_confirmation(self):
        self.create_connection()
        self.read_check()
        self.start()
        digest = self.digest()
        with patch('infrastructure.connection_probes.timezone.now',return_value=self.probe.expires_at+timedelta(seconds=1)):
            self.assertEqual(self.complete(digest).status_code,409)
            call_command('cleanup_storage_probes',stdout=io.StringIO())
        self.probe.refresh_from_db()
        self.connection.refresh_from_db()
        self.assertEqual(self.probe.state,'expired')
        self.assertNotEqual(self.connection.state,'ready')
        self.assertNotIn(self.probe.bucket,self.remote.buckets)

    def test_stale_cleanup_completion_cannot_overwrite_new_generation(self):
        from infrastructure.connection_probes import finish_cleanup,ConnectionRejected
        self.create_connection()
        self.read_check()
        self.start()
        StorageConnectionProbe.objects.filter(pk=self.probe.pk).update(state='cleaning',cleanup_generation=2)
        self.probe.state = 'cleaning'
        self.probe.cleanup_generation = 1
        with self.assertRaises(ConnectionRejected) as rejected:
            finish_cleanup(self.probe,self.owner,browser_verified=True)
        self.assertEqual(rejected.exception.code,'fixture_probe_superseded')
        self.probe.refresh_from_db()
        self.assertEqual((self.probe.state,self.probe.cleanup_generation),('cleaning',2))
        self.connection.refresh_from_db()
        self.assertNotEqual(self.connection.state,'ready')

    def test_reload_can_find_pending_probe_without_exposing_digest_or_signed_url(self):
        self.create_connection()
        self.read_check()
        self.start()
        response = self.client.get(self.base+'probe/')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['probes'][0]['id'],str(self.probe.pk))
        self.assertEqual(response.json()['probes'][0]['state'],'awaiting_browser')
        self.assertNotIn('expected_sha256',response.content.decode())
        self.assertNotIn('authorization',response.content.decode())

    def test_read_check_survives_operator_profile_rotation_without_rewriting_old_target(self):
        self.create_connection()
        before = (self.connection.endpoint_url,self.connection.bucket,self.connection.access_key_env)
        self.profiles['org-a-v1']['endpoint_url'] = 'https://new.example.invalid'
        self.profiles['org-a-v1']['bucket'] = 'new-data-target'
        self.read_check()
        self.connection.refresh_from_db()
        self.assertEqual((self.connection.endpoint_url,self.connection.bucket,self.connection.access_key_env),before)

    def test_read_check_can_retry_after_abandoned_lease(self):
        self.create_connection()
        type(self.connection).objects.filter(pk=self.connection.pk).update(state='verifying',verification_started_at=timezone.now()-timedelta(minutes=10))
        self.assertEqual(self.read_check().status_code,200)

    def test_retry_inside_live_read_check_lease_is_rejected(self):
        self.create_connection()
        type(self.connection).objects.filter(pk=self.connection.pk).update(state='verifying',verification_started_at=timezone.now())
        result = self.client.post(self.base+'verify/',{'reason':'Try concurrent live read check'},content_type='application/json')
        self.assertEqual(result.status_code,409)

    def test_tls_and_timeout_errors_have_distinct_sanitized_codes(self):
        self.create_connection()
        for error,code in ((SSLError(endpoint_url='https://storage.example.invalid',error='fixture-private-secret'),'tls_validation_failed'),(ReadTimeoutError(endpoint_url='https://storage.example.invalid'),'storage_unreachable')):
            with self.subTest(code=code),patch.object(self.remote,'head_bucket',side_effect=error):
                response = self.client.post(self.base+'verify/',{'reason':'Verify transport failure category'},content_type='application/json')
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.json()['connection']['last_error_code'],code)
            self.assertNotIn('fixture-private-secret',response.content.decode())
