"""Freshness lấy từ nguồn, không từ thời điểm HTTP trả lời."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase, AsyncClient, Client, override_settings
from django.utils import timezone

from infrastructure.models import StorageAccessGrant
from infrastructure.tests import InventoryFixture


def profile(cluster,**extra):
    return {'scope':'organization','tenant_id':str(cluster.tenant_id),'cluster_id':str(cluster.pk),'revision':1,'approved':True,'review_ref':'S4-isolated-fixture','edition':'community','provider_version':'fixture-1','metrics_schema':'seaweedfs_v1','endpoint_url':'https://metrics.example.invalid','allowed_networks':['10.31.0.0/24'],'token_env':'S4_FIXTURE_TOKEN','expected_labels':{'bluedrive_cluster_id':str(cluster.pk)},'queries':{name:{'expr':name,'timestamp_expr':'timestamp('+name+')'} for name in ('cluster_read_ready','cluster_write_ready','cluster_failed_disks','cluster_offline_nodes')},**extra}


def samples(**extra):
    return {'cluster_metrics':{'cluster_read_ready':1,'cluster_write_ready':1,'cluster_failed_disks':0,'cluster_offline_nodes':0,**extra},'node_metrics':{}}


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True,SECUREDRIVE_STORAGE_MONITORING_ENABLED=True)
class TelemetryAcceptanceTests(InventoryFixture,TestCase):
    def setUp(self):
        super().setUp()
        StorageAccessGrant.objects.create(membership=self.owner_member,permission='storage.monitor',granted_by=self.owner,reason='Read scoped monitoring evidence')

    def test_unconfigured_monitoring_is_unknown_without_zero_metrics_or_io(self):
        with patch('socket.getaddrinfo',side_effect=AssertionError('GET must not scrape private sources')):
            result = self.client.get(self.path('telemetry/',cluster=self.cluster))
        self.assertEqual(result.status_code,200,result.content)
        data = result.json()
        self.assertEqual(data['health']['status'],'unknown')
        self.assertTrue(data['health']['stale'])
        self.assertIsNone(data['health']['observed_at'])
        self.assertEqual(data['cluster_metrics'],{})

    def test_other_tenant_and_inventory_only_viewer_cannot_read_monitoring(self):
        self.assertEqual(self.client.get(self.path('telemetry/',cluster=self.other)).status_code,404)
        StorageAccessGrant.objects.create(membership=self.viewer_member,permission='storage.view',granted_by=self.owner,reason='Inventory only access fixture')
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.path('telemetry/',cluster=self.cluster)).status_code,403)

    def test_monitoring_flag_off_hides_endpoint(self):
        with override_settings(SECUREDRIVE_STORAGE_MONITORING_ENABLED=False):
            self.assertEqual(self.client.get(self.path('telemetry/',cluster=self.cluster)).status_code,404)

    def configured(self):
        self.cluster.edition,self.cluster.provider_version = 'community','fixture-1'
        self.cluster.save(update_fields=['edition','provider_version'])
        self.registry = self.settings(SECUREDRIVE_STORAGE_MONITORING_PROFILES={'fixture':profile(self.cluster)})
        self.registry.enable(); self.addCleanup(self.registry.disable)
        from infrastructure.prometheus import profile_for
        return profile_for(self.cluster)

    def test_generation_fence_rejects_late_success_and_profile_downgrade(self):
        from infrastructure.telemetry import claim_collection,publish_collection,snapshot_data
        from infrastructure.prometheus import MonitoringError
        plan = self.configured()
        first,second = claim_collection(self.cluster,plan),claim_collection(self.cluster,plan)
        now = timezone.now()
        self.assertTrue(publish_collection(self.cluster,plan,second,samples(cluster_write_ready=0),now))
        self.assertFalse(publish_collection(self.cluster,plan,first,samples(),now))
        self.assertEqual(snapshot_data(self.cluster)['health']['status'],'critical')
        with self.assertRaises(MonitoringError):
            claim_collection(self.cluster,{**plan,'fingerprint':'different'})

    def test_claim_locks_existing_snapshot_before_read_modify_save(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from infrastructure.telemetry import claim_collection
        plan = self.configured()
        claim_collection(self.cluster,plan)
        with CaptureQueriesContext(connection) as queries:
            claim_collection(self.cluster,plan)
        self.assertTrue(any('SELECT' in query['sql'] and 'infrastructure_storagetelemetrysnapshot' in query['sql'] and 'FOR UPDATE' in query['sql'] for query in queries))

    def test_stale_source_failure_and_recovery_preserve_values_and_incident_history(self):
        from infrastructure.telemetry import claim_collection,publish_collection,snapshot_data,sweep_stale
        from infrastructure.models import StorageAlert,StorageTelemetrySnapshot
        plan = self.configured(); now = timezone.now()
        token = claim_collection(self.cluster,plan)
        publish_collection(self.cluster,plan,token,samples(cluster_write_ready=0),now)
        token = claim_collection(self.cluster,plan)
        publish_collection(self.cluster,plan,token,error_code='source_request_failed')
        view = snapshot_data(self.cluster)
        self.assertEqual(view['health']['status'],'unknown')
        self.assertEqual(view['cluster_metrics']['cluster_write_ready'],0)
        self.assertEqual(StorageAlert.objects.filter(resolved_at__isnull=True).count(),2)
        StorageTelemetrySnapshot.objects.filter(cluster=self.cluster).update(observed_at=now-timedelta(seconds=200))
        self.assertEqual(sweep_stale(),1)
        self.assertEqual(sweep_stale(),0)
        publish_collection(self.cluster,plan,claim_collection(self.cluster,plan),samples(),timezone.now())
        self.assertEqual(snapshot_data(self.cluster)['health']['status'],'healthy')
        self.assertFalse(StorageAlert.objects.filter(resolved_at__isnull=True).exists())
        self.assertEqual(StorageAlert.objects.count(),3)

    def test_timestamp_regression_missing_samples_and_foreign_nodes_cannot_make_healthy(self):
        from infrastructure.telemetry import claim_collection,publish_collection,snapshot_data,collect
        plan = self.configured(); now = timezone.now()
        payload = samples(); payload['node_metrics'][str(self.other_node.pk)] = {'node_seaweedfs_up':1,'node_host_up':1}
        publish_collection(self.cluster,plan,claim_collection(self.cluster,plan),payload,now)
        self.assertEqual(snapshot_data(self.cluster)['nodes'],{})
        with patch('infrastructure.telemetry.fetch_metrics',return_value=(samples(),now-timedelta(seconds=10))):
            self.assertFalse(collect(self.cluster,plan))
        self.assertEqual(snapshot_data(self.cluster)['health']['status'],'unknown')
        publish_collection(self.cluster,plan,claim_collection(self.cluster,plan),samples(),now-timedelta(seconds=150))
        self.assertEqual(snapshot_data(self.cluster)['health']['status'],'unknown')

    def test_acknowledgement_is_versioned_idempotent_scoped_and_audited(self):
        from infrastructure.telemetry import claim_collection,publish_collection
        from infrastructure.models import StorageAlert,ClusterAuditEvent
        plan = self.configured()
        publish_collection(self.cluster,plan,claim_collection(self.cluster,plan),samples(cluster_write_ready=0),timezone.now())
        alert = StorageAlert.objects.get(code='write_quorum_lost')
        path = self.path(f'alerts/{alert.pk}/acknowledge/',cluster=self.cluster)
        data = {'expected_revision':5,'reason':'Investigating scoped incident'}
        self.assertEqual(self.client.post(path,data,content_type='application/json').status_code,409)
        data['expected_revision'] = 1
        self.assertEqual(self.client.post(path,data,content_type='application/json').status_code,200)
        self.assertTrue(self.client.post(path,data,content_type='application/json').json()['unchanged'])
        self.assertEqual(ClusterAuditEvent.objects.filter(action='storage.alert.acknowledged').count(),1)
        StorageAccessGrant.objects.filter(membership=self.owner_member,permission='storage.monitor').delete()
        self.assertEqual(self.client.post(path,data,content_type='application/json').status_code,403)

    def test_wsgi_fallback_and_rechecking_stream_session(self):
        from infrastructure.telemetry_api import authorized_event
        self.assertFalse(self.client.get(self.path('telemetry/',cluster=self.cluster)).json()['sse_available'])
        self.assertEqual(self.client.get(self.path('telemetry/stream/',cluster=self.cluster)).status_code,503)
        key = self.client.session.session_key
        with patch('infrastructure.telemetry_api.close_old_connections'):
            self.assertIsNotNone(authorized_event(key,self.owner.pk,self.cluster.pk,self.tenant.pk))
            StorageAccessGrant.objects.filter(membership=self.owner_member,permission='storage.monitor').delete()
            self.assertIsNone(authorized_event(key,self.owner.pk,self.cluster.pk,self.tenant.pk))


class PrometheusBoundaryTests(TestCase):
    def test_success_joins_values_with_their_source_timestamps_and_closes_transport(self):
        from infrastructure.prometheus import fetch_metrics,REQUIRED,MonitoringError
        from unittest.mock import Mock
        now = timezone.now()
        plan = {'stale_after_seconds':90,'expected_labels':{'bluedrive_cluster_id':'expected'},'queries':{name:{'expr':name,'timestamp_expr':'stamp-'+name} for name in REQUIRED}}
        def reply(pool,plan,expression,at):
            value = at.timestamp()-10 if expression.startswith('stamp-') else int(expression.endswith('ready'))
            return [{'metric':plan['expected_labels'],'value':[at.timestamp(),str(value)]}]
        pool = Mock()
        with patch('infrastructure.prometheus.make_pool',return_value=pool),patch('infrastructure.prometheus.query',side_effect=reply) as query:
            payload,observed = fetch_metrics(plan,set(),now)
        self.assertEqual(observed,now-timedelta(seconds=10))
        self.assertEqual(payload,samples())
        self.assertEqual(query.call_count,8)
        pool.close.assert_called_once()
        with patch('infrastructure.prometheus.make_pool',return_value=Mock()),patch('infrastructure.prometheus.query',return_value=[]):
            with self.assertRaisesRegex(MonitoringError,'source_samples_missing'): fetch_metrics(plan,set(),now)

    def test_source_body_deadline_is_bounded(self):
        from unittest.mock import Mock
        from infrastructure.prometheus import query,MonitoringError
        import os
        with patch.dict(os.environ,{'S4_FIXTURE_TOKEN':'fixture'}),patch('infrastructure.prometheus.time.monotonic',side_effect=[0,6]):
            with self.assertRaisesRegex(MonitoringError,'source_timeout'):
                query(Mock(urlopen=Mock(return_value=Mock(status=200,headers={}))),{'token_env':'S4_FIXTURE_TOKEN'},'fixture',timezone.now())

    def test_profiles_require_version_approval_tenant_and_labels(self):
        from types import SimpleNamespace
        import uuid
        from infrastructure.prometheus import profile_for,MonitoringError
        cluster = SimpleNamespace(pk=uuid.uuid4(),tenant_id=uuid.uuid4(),kind='enterprise',provider='s3',edition='community',provider_version='fixture-1')
        good = profile(cluster)
        for extra in ({'approved':False},{'tenant_id':str(uuid.uuid4())},{'provider_version':'different'},{'metrics_schema':'minio_v2'},{'endpoint_url':'https://user:password@metrics.example.invalid'},{'expected_labels':{}},{'queries':{}},{'capacity_thresholds':{'warning':95,'critical':80}}):
            with self.settings(SECUREDRIVE_STORAGE_MONITORING_PROFILES={'fixture':{**good,**extra}}):
                with self.assertRaises(MonitoringError): profile_for(cluster)
        with self.settings(SECUREDRIVE_STORAGE_MONITORING_PROFILES={'fixture':good}):
            with patch('socket.getaddrinfo',side_effect=AssertionError('Profile validation must not connect')):
                self.assertEqual(profile_for(cluster)['stale_after_seconds'],90)

    def test_vectors_reject_wrong_scope_ambiguity_and_invalid_numbers(self):
        from infrastructure.prometheus import parse_vector,MonitoringError,valid_value
        plan = {'expected_labels':{'bluedrive_cluster_id':'expected'}}
        good = {'metric':plan['expected_labels'],'value':[0,'1']}
        self.assertEqual(parse_vector([good],'cluster_read_ready',plan,set()),{'cluster':1})
        for rows in ([good,good],[{**good,'metric':{'bluedrive_cluster_id':'foreign'}}],[{**good,'value':[0,'NaN']}],[{**good,'value':[0,'2']}], [None]):
            with self.assertRaises(MonitoringError): parse_vector(rows,'cluster_read_ready',plan,set())
        for value in (True,-1,float('inf'),10**400): self.assertFalse(valid_value('raw_capacity_bytes',value))

    def test_actual_source_timestamp_is_required_even_with_current_evaluation_time(self):
        from infrastructure.prometheus import fetch_metrics,MonitoringError,REQUIRED
        now = timezone.now()
        plan = {'stale_after_seconds':90,'expected_labels':{'bluedrive_cluster_id':'expected'},'queries':{name:{'expr':name,'timestamp_expr':'stamp-'+name} for name in REQUIRED}}
        def reply(pool,plan,expression,at):
            value = at.timestamp()-120 if expression.startswith('stamp-') else 1
            return [{'metric':plan['expected_labels'],'value':[at.timestamp(),str(value)]}]
        from unittest.mock import Mock
        with patch('infrastructure.prometheus.make_pool',return_value=Mock()),patch('infrastructure.prometheus.query',side_effect=reply):
            with self.assertRaisesRegex(MonitoringError,'source_samples_stale'):
                fetch_metrics(plan,set(),now)

    def test_http_rejects_redirect_auth_errors_oversize_and_secret_exceptions(self):
        import os
        from unittest.mock import Mock
        from infrastructure.prometheus import query,MonitoringError
        plan = {'token_env':'S4_FIXTURE_TOKEN'}
        with patch.dict(os.environ,{'S4_FIXTURE_TOKEN':'fixture-not-a-secret'}):
            for status,raw,code in ((302,b'{}','source_response_rejected'),(403,b'{}','source_identity_rejected'),(200,b'x'*524289,'source_response_too_large'),(200,b'{"status":"success","data":{"resultType":"vector","result":[]}}','')):
                response = Mock(status=status,headers={},read1=Mock(side_effect=[raw,b'']))
                pool = Mock(urlopen=Mock(return_value=response))
                if code:
                    with self.assertRaisesRegex(MonitoringError,code): query(pool,plan,'fixture',timezone.now())
                else: self.assertEqual(query(pool,plan,'fixture',timezone.now()),[])
                self.assertFalse(pool.urlopen.call_args.kwargs['redirect'])
                response.close.assert_called_once()
            with self.assertRaisesRegex(MonitoringError,'source_request_failed'):
                query(Mock(urlopen=Mock(side_effect=RuntimeError('private details'))),plan,'fixture',timezone.now())


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True,SECUREDRIVE_STORAGE_MONITORING_ENABLED=True)
class TelemetryStreamTests(InventoryFixture,TransactionTestCase):
    serialized_rollback = True
    def setUp(self):
        super().setUp()
        StorageAccessGrant.objects.create(membership=self.owner_member,permission='storage.monitor',granted_by=self.owner,reason='Stream test scope access')

    def test_asgi_stream_resync_cursor_revoke_and_password_change(self):
        from asgiref.sync import async_to_sync,sync_to_async
        from infrastructure.telemetry_api import authorized_event
        key = self.client.session.session_key
        browser = AsyncClient(); browser.cookies = self.client.cookies
        path = self.path('telemetry/stream/',cluster=self.cluster)
        async def consume():
            response = await browser.get(path)
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.is_async)
            self.assertEqual(response['X-Accel-Buffering'],'no')
            chunks = aiter(response.streaming_content)
            first = await anext(chunks)
            self.assertIn(b'event: resync',first)
            self.assertNotIn(b'private',first)
            await sync_to_async(StorageAccessGrant.objects.filter(membership=self.owner_member,permission='storage.monitor').delete)()
            with patch('infrastructure.telemetry_api.asyncio.sleep',return_value=None):
                self.assertIn(b'event: access_revoked',await anext(chunks))
            await chunks.aclose()
            await sync_to_async(response.close)()
        async_to_sync(consume)()
        StorageAccessGrant.objects.create(membership=self.owner_member,permission='storage.monitor',granted_by=self.owner,reason='Restore stream test scope')
        response = async_to_sync(browser.get)(path,headers={'Last-Event-ID':str(self.other.pk)+':1:0'})
        self.assertEqual(response.status_code,400)
        self.owner.set_password('changed-fixture-password'); self.owner.save(update_fields=['password'])
        self.assertIsNone(authorized_event(key,self.owner.pk,self.cluster.pk,self.tenant.pk))

    def test_csrf_and_unauthenticated_monitoring_are_denied(self):
        self.assertEqual(Client().get(self.path('telemetry/',cluster=self.cluster)).status_code,403)
        strict = Client(enforce_csrf_checks=True); strict.force_login(self.owner)
        import uuid
        path = self.path(f'alerts/{uuid.uuid4()}/acknowledge/',cluster=self.cluster)
        self.assertEqual(strict.post(path,{},content_type='application/json').status_code,403)
