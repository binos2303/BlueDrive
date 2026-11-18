"""Kho Organization được chọn trước mọi ghi mới; fixture không gọi provider thật."""
import hashlib
import io
import secrets
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, OrganizationIdentity, QuotaAccount, Tenant, Workspace
from accounts.services import provision_organization_drive
from files.finalization import finalize_verified_upload
from files.models import File, StorageConfig, StorageLocation, UploadSession
from files.services import clone_encrypted_file_with_quota
from files.storage_adapters.base import MultipartUpload, ObjectStat, StorageAdapter, StorageConfigurationError
from files.storage_routing import adapter_for_location, adapter_for_upload, upload_target
from folders.models import Folder
from infrastructure.models import StorageBinding, StorageCluster, StorageConnectionRevision


class OrganizationStorageIsolationTests(TestCase):
    def setUp(self):
        self.operator = get_user_model().objects.create_superuser(username='storage-operator')
        self.tenant = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name='Managed Organization')
        self.employee = get_user_model()(username='storage-employee', is_active=True)
        self.employee._skip_personal_tenant_provisioning = True
        self.employee.set_password(secrets.token_urlsafe(32))
        self.employee.save()
        self.identity = OrganizationIdentity.objects.create(user=self.employee, tenant=self.tenant,
                                                             invited_by=self.operator, activated_at=timezone.now())
        Membership.objects.create(user=self.employee, tenant=self.tenant, role=Membership.Role.MEMBER)
        self.drive = provision_organization_drive(self.identity)
        QuotaAccount.objects.create(tenant=self.tenant, scope=QuotaAccount.Scope.TENANT, limit_bytes=4096)
        QuotaAccount.objects.create(tenant=self.tenant, scope=QuotaAccount.Scope.MEMBER,
                                    user=self.employee, limit_bytes=4096)
        self.client.force_login(self.employee)
        self.payload = b'organization fixture\n'

    def adapter(self):
        adapter = Mock(spec=StorageAdapter)
        adapter.create_object_key.side_effect = lambda purpose: f'{purpose}/{uuid4().hex}'
        adapter.initiate_multipart.return_value = MultipartUpload('fixture-multipart')
        adapter.publish_verified_object.return_value = ObjectStat(size_bytes=len(self.payload), version_id='fixture-version')
        return adapter

    def create_upload(self, *, workspace=None, key=None):
        return self.client.post(reverse('api-upload-create'),
            {'name': 'fixture.txt', 'size_bytes': len(self.payload),
             'sha256': hashlib.sha256(self.payload).hexdigest(), 'workspace_id': str((workspace or self.drive).pk)},
            content_type='application/json', HTTP_IDEMPOTENCY_KEY=key or str(uuid4()))

    def binding(self, *, ready=True):
        now = timezone.now()
        cluster = StorageCluster.objects.create(kind='enterprise', tenant=self.tenant, slug='fixture-storage',
            display_name='Organization fixture storage', state='ready', verified_at=now, created_by=self.operator)
        connection = StorageConnectionRevision.objects.create(cluster=cluster, revision=1,
            profile_id='fixture-profile', request_digest='fixture', profile_digest='fixture',
            endpoint_url='https://organization.example.invalid', public_endpoint_url='https://objects.example.invalid',
            bucket='organization-fixture', access_key_env='FIXTURE_ORG_ACCESS', secret_key_env='FIXTURE_ORG_SECRET',
            state='ready' if ready else 'draft', read_verified_at=now if ready else None,
            verified_at=now if ready else None, created_by=self.operator)
        config = StorageConfig.objects.create(tenant=self.tenant, provider='s3', endpoint=connection.endpoint_url)
        StorageBinding.objects.create(tenant=self.tenant, scope='tenant', cluster=cluster, storage_config=config,
            connection=connection, state='active' if ready else 'draft', active_since=now if ready else None)
        return connection, config

    def assert_no_new_write(self):
        self.assertFalse(UploadSession.objects.exists())
        self.assertFalse(File.objects.exists())
        self.assertFalse(Folder.objects.exists())
        self.assertFalse(QuotaAccount.objects.filter(reserved_bytes__gt=0).exists())

    @override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=False)
    def test_managed_routing_off_never_prepares_global_adapter_or_reserves_quota(self):
        adapter = self.adapter()
        with patch('files.upload_api.get_storage_adapter', return_value=adapter) as factory:
            response = self.create_upload()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'organization_storage_unavailable')
        factory.assert_not_called()
        adapter.initiate_multipart.assert_not_called()
        self.assert_no_new_write()

    @override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=True)
    def test_missing_or_unverified_binding_fails_closed_before_new_session(self):
        for configured in (False, True):
            with self.subTest(binding=configured):
                if configured:
                    self.binding(ready=False)
                with patch('files.upload_api.get_storage_adapter') as factory:
                    response = self.create_upload()
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['code'], 'storage_binding_unavailable')
                factory.assert_not_called()
                self.assert_no_new_write()

    @override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=True)
    def test_verified_binding_pins_new_upload_and_finalization_keeps_it_when_routing_turns_off(self):
        connection, config = self.binding()
        adapter = self.adapter()
        with patch('files.upload_api.get_storage_adapter', return_value=adapter) as prepare:
            response = self.create_upload()
        self.assertEqual(response.status_code, 201)
        prepare.assert_called_once_with(connection=connection)
        upload = UploadSession.objects.get(pk=response.json()['upload_id'])
        self.assertEqual((upload.storage_connection_id, upload.storage_config_id, upload.endpoint_config_version),
                         (connection.pk, config.pk, connection.revision))
        upload.state = UploadSession.State.VERIFYING
        upload.save(update_fields=['state', 'updated_at'])
        StorageBinding.objects.filter(tenant=self.tenant).update(state='retired')
        with override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=False), \
                patch('files.storage_adapters.get_storage_adapter', return_value=adapter) as pinned:
            result = finalize_verified_upload(upload, io.BytesIO(self.payload), self.employee,
                verified_sha256=hashlib.sha256(self.payload).hexdigest())
        location = StorageLocation.objects.get(file_version__file_id=result['file_id'])
        self.assertEqual(location.storage_connection_id, connection.pk)
        self.assertEqual(location.storage_config_id, config.pk)
        pinned.assert_called_once_with(connection=connection)
        adapter.publish_verified_object.assert_called_once()

    @override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=True)
    def test_revision_disabled_during_copy_cannot_publish(self):
        connection, _config = self.binding()
        adapter = self.adapter()
        with patch('files.upload_api.get_storage_adapter', return_value=adapter):
            response = self.create_upload()
        self.assertEqual(response.status_code, 201)
        upload = UploadSession.objects.get(pk=response.json()['upload_id'])
        UploadSession.objects.filter(pk=upload.pk).update(state=UploadSession.State.VERIFYING)
        published = adapter.publish_verified_object.return_value

        def disable_revision(*args, **kwargs):
            StorageConnectionRevision.objects.filter(pk=connection.pk).update(state='disabled')
            return published

        adapter.publish_verified_object.side_effect = disable_revision
        with patch('files.storage_adapters.get_storage_adapter', return_value=adapter) as pinned:
            with self.assertRaises(StorageConfigurationError):
                finalize_verified_upload(upload, io.BytesIO(self.payload), self.employee,
                    verified_sha256=hashlib.sha256(self.payload).hexdigest())
            self.assertIs(adapter_for_upload(upload, fallback=Mock(), cleanup=True), adapter)
        self.assertTrue(all(call.kwargs['connection'].pk == connection.pk for call in pinned.call_args_list))
        self.assertFalse(File.objects.filter(workspace=self.drive).exists())
        self.assertFalse(StorageLocation.objects.filter(tenant=self.tenant).exists())

    @override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=False)
    def test_unpinned_managed_session_cannot_mint_new_writes_but_retains_original_cleanup(self):
        config = StorageConfig.objects.create(tenant=self.tenant, provider='s3',
                                             endpoint='https://legacy.example.invalid')
        session = UploadSession.objects.create(tenant=self.tenant, workspace=self.drive, initiated_by=self.employee,
            client_name='fixture.txt', expected_size_bytes=1,
            expires_at=timezone.now() + timedelta(hours=1))
        self.assertEqual((session.storage_config_id, session.storage_connection_id, session.endpoint_config_version),
                         (None, None, None))
        fallback = Mock()
        with self.assertRaises(StorageConfigurationError):
            adapter_for_upload(session, fallback=fallback)
        fallback.assert_not_called()
        with override_settings(SECUREDRIVE_STORAGE_ENDPOINT_URL=config.endpoint):
            self.assertIs(adapter_for_upload(session, fallback=fallback, cleanup=True), fallback.return_value)
            location = SimpleNamespace(storage_connection_id=None, storage_config=config)
            self.assertIs(adapter_for_location(location, fallback=fallback), fallback.return_value)

    @override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=True)
    def test_cross_tenant_selector_and_pinned_connection_are_denied(self):
        self.binding()
        other = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name='Other Organization')
        foreign_workspace = Workspace.objects.create(tenant=other, name='Other workspace', slug='other')
        with patch('files.upload_api.get_storage_adapter') as factory:
            response = self.create_upload(workspace=foreign_workspace)
        self.assertEqual(response.status_code, 404)
        factory.assert_not_called()
        for routing in (False, True):
            with self.subTest(routing=routing), override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=routing):
                with self.assertRaises(StorageConfigurationError) as caught:
                    upload_target(self.tenant, foreign_workspace)
                self.assertEqual(caught.exception.code, 'storage_scope_mismatch')
        foreign_cluster = SimpleNamespace(kind='enterprise', tenant_id=other.pk)
        record = SimpleNamespace(storage_connection_id=uuid4(), tenant=self.tenant,
                                 storage_connection=SimpleNamespace(cluster=foreign_cluster))
        with patch('files.storage_adapters.get_storage_adapter') as factory:
            with self.assertRaises(StorageConfigurationError):
                adapter_for_upload(record, fallback=factory)
        factory.assert_not_called()

    @override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=False)
    def test_personal_and_unmanaged_business_keep_legacy_routing_and_personal_upload(self):
        personal = get_user_model().objects.create_user(username='personal-fixture')
        tenant = personal.personal_tenant
        drive = tenant.workspaces.get(is_default=True)
        self.assertEqual(upload_target(tenant, drive), {})
        unmanaged = Tenant.objects.create(kind=Tenant.Kind.BUSINESS, name='Legacy business')
        workspace = Workspace.objects.create(tenant=unmanaged, name='Legacy workspace', slug='legacy')
        self.assertEqual(upload_target(unmanaged, workspace), {})
        self.client.force_login(personal)
        adapter = self.adapter()
        with patch('files.upload_api.get_storage_adapter', return_value=adapter) as factory:
            response = self.create_upload(workspace=drive)
        self.assertEqual(response.status_code, 201)
        factory.assert_called_once_with()
        self.assertIsNone(UploadSession.objects.get(pk=response.json()['upload_id']).storage_connection_id)

    @override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=False)
    def test_legacy_file_folder_and_copy_cannot_write_managed_media(self):
        for name, data in (
            ('file_upload', {'file_path': SimpleUploadedFile('fixture.txt', self.payload), 'workspace_id': str(self.drive.pk)}),
            ('folder_upload', {'files': SimpleUploadedFile('fixture.txt', self.payload),
                               'relative_paths': ['root/fixture.txt'], 'workspace_id': str(self.drive.pk)}),
        ):
            with self.subTest(route=name), patch('django.core.files.storage.FileSystemStorage.save') as save:
                response = self.client.post(reverse(name), data)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['code'], 'organization_storage_unavailable')
                save.assert_not_called()
                self.assert_no_new_write()
        source = File.objects.create(tenant=self.tenant, workspace=self.drive, owner=self.employee,
                                     file_name='legacy.txt', file_size=1)
        with patch('django.core.files.storage.FileSystemStorage.save') as save:
            with self.assertRaises(StorageConfigurationError):
                clone_encrypted_file_with_quota(source, owner=self.employee, folder=None,
                                               file_name='copy.txt', tenant=self.tenant)
            save.assert_not_called()
        self.assertFalse(UploadSession.objects.exists())

    @override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=False)
    def test_legacy_clipboard_copies_fail_before_metadata_quota_or_media_writes(self):
        source = Folder.objects.create(tenant=self.tenant, workspace=self.drive, owner=self.employee,
                                       folder_name='Source')
        Folder.objects.create(tenant=self.tenant, workspace=self.drive, owner=self.employee,
                              folder_name='Child', parent=source)
        destination = Folder.objects.create(tenant=self.tenant, workspace=self.drive, owner=self.employee,
                                            folder_name='Destination')
        drive_file = File.objects.create(tenant=self.tenant, workspace=self.drive, owner=self.employee,
                                         folder=source, file_name='legacy.txt', file_size=1)
        before_files = list(File.objects.values_list('pk', 'folder_id', 'file_size'))
        before_folders = list(Folder.objects.order_by('pk').values_list('pk', 'parent_id'))
        before_quota = list(QuotaAccount.objects.order_by('pk').values_list('pk', 'used_bytes', 'reserved_bytes'))
        for route, clipboard in (
            ('file_paste', {'type': 'file', 'file_id': drive_file.pk}),
            ('folder_paste', {'type': 'folder', 'folder_id': source.pk}),
        ):
            with self.subTest(route=route):
                session = self.client.session
                session['clipboard'] = clipboard
                session.save()
                with patch('django.core.files.storage.FileSystemStorage.save') as save, \
                        patch('folders.views.Folder.objects.create') as create_folder, \
                        patch('files.services.UploadSession.objects.create') as create_upload:
                    response = self.client.post(reverse(route), {'folder_id': destination.pk})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['code'], 'organization_storage_unavailable')
                save.assert_not_called()
                create_folder.assert_not_called()
                create_upload.assert_not_called()
                self.assertEqual(list(File.objects.values_list('pk', 'folder_id', 'file_size')), before_files)
                self.assertEqual(list(Folder.objects.order_by('pk').values_list('pk', 'parent_id')), before_folders)
                self.assertEqual(list(QuotaAccount.objects.order_by('pk').values_list('pk', 'used_bytes', 'reserved_bytes')), before_quota)
                self.assertFalse(UploadSession.objects.exists())

    @override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=False)
    def test_duplicate_new_object_fails_structured_before_decrypt_or_metadata(self):
        source = File.objects.create(tenant=self.tenant, workspace=self.drive, owner=self.employee,
                                     file_name='legacy.txt', file_size=1)
        with patch('files.views._decrypt_file') as decrypt:
            response = self.client.post(reverse('drive_items_duplicate_api'),
                {'file_ids': [source.pk], 'folder_ids': [], 'workspace_id': str(self.drive.pk)},
                content_type='application/json')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'organization_storage_unavailable')
        decrypt.assert_not_called()
        self.assertEqual(File.objects.count(), 1)
        self.assertFalse(UploadSession.objects.exists())
