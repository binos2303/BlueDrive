"""Binding mới chỉ áp dụng cho upload mới; quota và dữ liệu cũ giữ nguyên đích."""
import hashlib
import io
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.models import QuotaAccount, Workspace
from files.finalization import finalize_verified_upload
from files.models import File, FileVersion, QuotaReservation, StorageLocation, UploadSession
from files.permanent_delete import permanently_delete_files
from files.storage_adapters.base import MultipartUpload, ObjectStat, PresignedRequest, StorageAdapter, StorageConfigurationError
from files.storage_routing import adapter_for_location, adapter_for_upload, upload_target
from infrastructure.test_connections import WorkflowFixture


@override_settings(SECUREDRIVE_STORAGE_ENDPOINT_URL='http://original-storage:9000')
class LegacyRoutingTests(SimpleTestCase):
    def legacy_record(self, endpoint):
        return SimpleNamespace(
            storage_connection_id=None, storage_config_id=1,
            storage_config=SimpleNamespace(endpoint=endpoint),
        )

    def test_endpoint_change_blocks_legacy_reads_writes_and_cleanup(self):
        record = self.legacy_record('http://original-storage:9000')
        with override_settings(SECUREDRIVE_STORAGE_ENDPOINT_URL='http://new-storage:8333'):
            for resolver in (adapter_for_upload, adapter_for_location):
                for cleanup in (False, True):
                    with self.subTest(resolver=resolver.__name__, cleanup=cleanup):
                        fallback = Mock()
                        with self.assertRaises(StorageConfigurationError):
                            resolver(record, fallback=fallback, cleanup=cleanup)
                        fallback.assert_not_called()

    def test_unchanged_legacy_endpoint_keeps_compatibility(self):
        for endpoint in ('', 'http://original-storage:9000', 'http://original-storage:9000/'):
            for resolver in (adapter_for_upload, adapter_for_location):
                with self.subTest(endpoint=endpoint, resolver=resolver.__name__):
                    fallback = Mock()
                    self.assertIs(resolver(self.legacy_record(endpoint), fallback=fallback), fallback.return_value)
                    fallback.assert_called_once_with()

    def test_legacy_upload_without_storage_config_keeps_compatibility(self):
        fallback = Mock()
        record = SimpleNamespace(storage_connection_id=None, storage_config_id=None)
        self.assertIs(adapter_for_upload(record, fallback=fallback), fallback.return_value)


@override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=True)
class StrictRoutingGuardsTests(SimpleTestCase):
    """Khi bật routing, mọi caller thiếu revision phải thất bại, kể cả cleanup."""

    def test_unpinned_upload_does_not_call_legacy_fallback(self):
        record = SimpleNamespace(storage_connection_id=None, storage_config_id=None)
        for cleanup in (False, True):
            with self.subTest(cleanup=cleanup):
                fallback = Mock()
                with self.assertRaises(StorageConfigurationError):
                    adapter_for_upload(record, fallback=fallback, cleanup=cleanup)
                fallback.assert_not_called()

    def test_unpinned_location_does_not_call_legacy_fallback(self):
        record = SimpleNamespace(storage_connection_id=None, storage_config=None)
        for cleanup in (False, True):
            with self.subTest(cleanup=cleanup):
                fallback = Mock()
                with self.assertRaises(StorageConfigurationError):
                    adapter_for_location(record, fallback=fallback, cleanup=cleanup)
                fallback.assert_not_called()

    def test_global_adapter_without_connection_is_rejected(self):
        from files.storage_adapters.factory import get_storage_adapter

        with self.assertRaises(StorageConfigurationError):
            get_storage_adapter()


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True,SECUREDRIVE_STORAGE_LAB_PROBES_ENABLED=True,SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=True)
class PinnedRoutingTests(WorkflowFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.space = Workspace.objects.create(tenant=self.tenant,name='Pinned workspace',slug='pinned-workspace',created_by=self.owner)
        self.quota = QuotaAccount.objects.get(workspace=self.space,scope='workspace')
        self.quota.limit_bytes = 100
        self.quota.save(update_fields=['limit_bytes'])
        self.payload = b'pinned transfer\n'

    def make_ready(self):
        self.create_connection()
        self.read_check()
        self.start()
        result = self.complete()
        self.assertEqual(result.status_code,200,result.content)
        self.connection.refresh_from_db()
        return self.connection

    def bind(self,connection,generation):
        response = self.client.patch(self.path('binding/'),{'connection_id':str(connection.pk),'expected_generation':generation,'reason':'Prepare verified storage binding'},content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        return response.json()['binding']['generation']

    def adapters(self,first,second=None):
        targets = {}
        for conn in (first,second):
            if conn is None:
                continue
            adapter = Mock(spec=StorageAdapter)
            adapter.create_object_key.side_effect = lambda scope: f'{scope}/{uuid.uuid4().hex}'
            adapter.initiate_multipart.return_value = MultipartUpload('fixture-upload-'+str(conn.pk))
            adapter.create_part_upload_url.return_value = PresignedRequest('https://objects.example.invalid/mock','PUT',{})
            adapter.publish_verified_object.return_value = ObjectStat(size_bytes=len(self.payload),version_id='published-version')
            adapter.open_object.return_value = io.BytesIO(self.payload)
            targets[conn.pk] = adapter
        def factory(*,connection=None,**kwargs):
            if connection is None:
                raise AssertionError('Pinned operation must never use global fallback')
            return targets[connection.pk]
        self.enterContext(patch('files.storage_adapters.get_storage_adapter',side_effect=factory))
        self.enterContext(patch('files.upload_api.get_storage_adapter',side_effect=factory))
        return targets

    def upload(self,key='pinned-upload-key'):
        return self.client.post('/files/api/uploads/',{'name':'pinned.txt','size_bytes':len(self.payload),'sha256':hashlib.sha256(self.payload).hexdigest(),'workspace_id':str(self.space.pk)},content_type='application/json',HTTP_IDEMPOTENCY_KEY=key)

    def published_upload(self):
        connection = self.make_ready()
        self.bind(connection, 0)
        adapter = self.adapters(connection)[connection.pk]
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.content)
        session = UploadSession.objects.get(pk=response.json()['upload_id'])
        complete = self.client.post(f'/files/api/uploads/{session.pk}/complete/',
            {'parts': [{'part_number': 1, 'etag': 'fixture'}]}, content_type='application/json')
        self.assertEqual(complete.status_code, 202, complete.content)
        result = finalize_verified_upload(session, io.BytesIO(self.payload), self.owner,
            verified_sha256=hashlib.sha256(self.payload).hexdigest())
        session.refresh_from_db()
        return session, File.objects.get(pk=result['file_id']), adapter

    def test_pinned_permanent_delete_preserves_successful_upload_and_consumed_quota_history(self):
        session, drive_file, adapter = self.published_upload()
        original_state, original_connection = session.state, session.storage_connection_id
        reservations = list(session.quota_reservations.values_list('pk', 'state'))
        self.assertTrue(reservations)
        self.assertTrue(all(state == QuotaReservation.State.CONSUMED for _, state in reservations))
        adapter.delete_object.reset_mock()
        self.assertEqual(permanently_delete_files([drive_file]), 1)
        self.assertFalse(File.objects.filter(pk=drive_file.pk).exists())
        self.assertFalse(FileVersion.objects.filter(file_id=drive_file.pk).exists())
        session.refresh_from_db()
        self.assertIsNone(session.file_id)
        self.assertEqual((session.state, session.storage_connection_id), (original_state, original_connection))
        self.assertEqual(list(session.quota_reservations.values_list('pk', 'state')), reservations)
        self.quota.refresh_from_db()
        self.assertEqual((self.quota.used_bytes, self.quota.reserved_bytes), (0, 0))
        adapter.delete_object.assert_called_once()
        UploadSession.objects.filter(pk=session.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        call_command('cleanup_uploads', stdout=io.StringIO())
        session.refresh_from_db()
        self.assertEqual((session.state, session.file_id, session.object_key, session.provider_upload_id),
            (original_state, None, '', ''))

    def test_pinned_successful_upload_cannot_detach_before_versions_are_removed_or_reattach(self):
        session, drive_file, _adapter = self.published_upload()
        with self.assertRaises(IntegrityError), transaction.atomic():
            UploadSession.objects.filter(pk=session.pk).update(file=None)
        other_file = File.objects.create(tenant=drive_file.tenant, workspace=drive_file.workspace,
            owner=drive_file.owner, file_name='another-file.txt', file_size=0)
        other_version = FileVersion.objects.create(tenant=drive_file.tenant, file=other_file,
            version_number=1, state='available', is_current=True, size_bytes=0)
        StorageLocation.objects.create(tenant=drive_file.tenant, file_version=other_version,
            storage_config=session.storage_config, storage_connection=session.storage_connection,
            object_ref='primary/' + uuid.uuid4().hex, state='available', size_bytes=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            UploadSession.objects.filter(pk=session.pk).update(file=other_file)
        with self.assertRaises(IntegrityError), transaction.atomic():
            UploadSession.objects.create(tenant=session.tenant, workspace=session.workspace,
                initiated_by=self.owner, client_name='invalid-publication.txt', expected_size_bytes=0,
                storage_config=session.storage_config, storage_connection=session.storage_connection,
                endpoint_config_version=session.endpoint_config_version, state='available', expires_at=timezone.now())

    def test_upload_binding_flip_preserves_original_target_through_publish_read_and_cleanup(self):
        first = self.make_ready()
        generation = self.bind(first,0)
        targets = self.adapters(first)
        response = self.upload()
        self.assertEqual(response.status_code,201,response.content)
        session = UploadSession.objects.get(pk=response.json()['upload_id'])
        self.assertEqual(session.storage_connection_id,first.pk)
        self.quota.refresh_from_db()
        self.assertEqual(self.quota.reserved_bytes,len(self.payload))

        # Revision mới giữ cùng chủ sở hữu; không sửa profile/target cũ.
        self.profiles['org-a-v2'] = {**self.profiles['org-a-v1'],'bucket':'org-a-data-v2','endpoint_url':'https://minio-b.example.invalid','public_endpoint_url':'https://objects-b.example.invalid'}
        self.remote.buckets['org-a-data-v2'] = {**self.remote.buckets['org-a-data'],'objects':{}}
        result = self.client.post(self.path('connections/',cluster=first.cluster),{'profile_id':'org-a-v2','reason':'Rotate approved connection revision'},content_type='application/json',HTTP_IDEMPOTENCY_KEY='second-connection-revision')
        self.assertEqual(result.status_code,201,result.content)
        self.connection = type(first).objects.get(pk=result.json()['connection']['id'])
        self.base = self.path(f'connections/{self.connection.pk}/',cluster=self.connection.cluster)
        self.read_check()
        self.start()
        self.assertEqual(self.complete().status_code,200)
        second = self.connection
        self.bind(second,generation)
        # Override factory sau probe; hai adapter riêng giúp phát hiện nhầm đích.
        targets = self.adapters(first,second)
        replay = self.upload()
        self.assertEqual(replay.status_code,200,replay.content)
        self.assertEqual(replay.json()['upload_id'],str(session.pk))
        self.assertEqual(targets[second.pk].initiate_multipart.call_count,0)
        url = f'/files/api/uploads/{session.pk}/'
        auth = self.client.post(url+'parts/authorizations/',{'part_numbers':[1]},content_type='application/json')
        self.assertEqual(auth.status_code,200,auth.content)
        targets[first.pk].create_part_upload_url.assert_called_once()
        targets[second.pk].create_part_upload_url.assert_not_called()
        complete = self.client.post(url+'complete/',{'parts':[{'part_number':1,'etag':'fixture'}]},content_type='application/json')
        self.assertEqual(complete.status_code,202,complete.content)
        session.refresh_from_db()
        result = finalize_verified_upload(session,io.BytesIO(self.payload),self.owner,verified_sha256=hashlib.sha256(self.payload).hexdigest())
        location = StorageLocation.objects.get(file_version__file_id=result['file_id'])
        self.assertEqual(location.storage_connection_id,first.pk)
        targets[first.pk].publish_verified_object.assert_called_once()
        targets[second.pk].publish_verified_object.assert_not_called()
        with override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=False):
            self.assertIs(adapter_for_location(location,fallback=lambda: self.fail('legacy fallback')),targets[first.pk])
        self.quota.refresh_from_db()
        self.assertEqual((self.quota.used_bytes,self.quota.reserved_bytes),(len(self.payload),0))
        next_upload = self.upload('pinned-new-upload')
        self.assertEqual(next_upload.status_code,201,next_upload.content)
        self.assertEqual(UploadSession.objects.get(pk=next_upload.json()['upload_id']).storage_connection_id,second.pk)
        self.assertEqual(self.client.post(f"/files/api/uploads/{next_upload.json()['upload_id']}/abort/").status_code,200)
        targets[second.pk].abort_multipart.assert_called_once()
        UploadSession.objects.filter(pk=session.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        targets[first.pk].delete_object.reset_mock()
        call_command('cleanup_uploads',stdout=io.StringIO())
        self.assertNotIn(location.object_ref,[call.args[0] for call in targets[first.pk].delete_object.call_args_list])
        self.assertTrue(File.objects.filter(pk=result['file_id']).exists())

    def test_missing_business_binding_fails_before_reservation_or_storage(self):
        with patch('files.upload_api.get_storage_adapter') as factory,self.assertLogs('files.upload_api',level='ERROR'):
            response = self.upload()
        self.assertEqual(response.status_code,503)
        factory.assert_not_called()
        self.assertFalse(UploadSession.objects.exists())
        self.quota.refresh_from_db()
        self.assertEqual(self.quota.reserved_bytes,0)

    def test_database_rejects_target_change_and_publication_without_matching_location(self):
        first = self.make_ready()
        self.bind(first,0)
        self.adapters(first)
        response = self.upload()
        self.assertEqual(response.status_code,201,response.content)
        session = UploadSession.objects.get(pk=response.json()['upload_id'])
        with self.assertRaises(IntegrityError),transaction.atomic():
            UploadSession.objects.filter(pk=session.pk).update(storage_connection=None,storage_config=None,endpoint_config_version=None)
        with self.assertRaises(IntegrityError),transaction.atomic():
            UploadSession.objects.filter(pk=session.pk).update(state='available')

    def test_disabled_pinned_target_fails_closed_instead_of_using_global_storage(self):
        first = self.make_ready()
        self.bind(first,0)
        self.adapters(first)
        response = self.upload()
        session = UploadSession.objects.get(pk=response.json()['upload_id'])
        type(first).objects.filter(pk=first.pk).update(state='disabled')
        session = UploadSession.objects.get(pk=session.pk)
        fallback = Mock()
        with self.assertRaises(StorageConfigurationError):
            adapter_for_upload(session,fallback=fallback)
        fallback.assert_not_called()

    def test_new_uploads_stop_after_failed_storage_diagnostic(self):
        first = self.make_ready()
        self.bind(first,0)
        type(first).objects.filter(pk=first.pk).update(last_error_code='storage_identity_rejected')
        with self.assertRaises(StorageConfigurationError):
            upload_target(self.tenant,self.space)
