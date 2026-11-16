"""Acceptance S2: profile được cấp phép, không URL/secret từ browser."""
import os
import hashlib
import io
from types import SimpleNamespace
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError, SSLError
from django.core.management import call_command
from django.db import IntegrityError, transaction

from django.test import TestCase, override_settings
from infrastructure.models import StorageAccessGrant, StorageConnectionRevision, StorageConnectionProbe, StorageBinding
from infrastructure.tests import InventoryFixture
from files.storage_routing import upload_target
from files.storage_adapters.base import StorageConfigurationError


class ConnectionFixture(InventoryFixture):
    def setUp(self):
        super().setUp()
        StorageAccessGrant.objects.create(membership=self.owner_member, permission='storage.configure', granted_by=self.owner, reason='Manage approved connection profiles')
        self.profiles = {'org-a-v1':{
            'scope':'organization', 'tenant_id':str(self.tenant.pk),
            'label':'Organization A storage', 'provider':'s3', 'edition':'community', 'provider_version':'fixture-release',
            'endpoint_url':'https://s3-a.example.invalid', 'public_endpoint_url':'https://objects-a.example.invalid',
            'bucket':'org-a-data', 'region':'us-east-1', 'allowed_networks':['10.30.0.10/32'],
            'access_key_env':'SCC_A_ACCESS_V1', 'secret_key_env':'SCC_A_SECRET_V1', 'lab':True,
            'server_side_encryption':'AES256',
        }}
        self.enterContext(override_settings(SECUREDRIVE_STORAGE_CONNECTION_PROFILES=self.profiles))
        self.enterContext(patch.dict(os.environ, {'SCC_A_ACCESS_V1':'fixture-access', 'SCC_A_SECRET_V1':'fixture-private-secret'}))
        self.dns = self.enterContext(patch('socket.getaddrinfo', return_value=[(2,1,6,'',('10.30.0.10',443))]))

    def connect(self, body=None):
        return self.client.post(self.path('clusters/connect/'), body or {'display_name':'Connected A','slug':'connected-a','profile_id':'org-a-v1','reason':'Register approved storage target'}, content_type='application/json', HTTP_IDEMPOTENCY_KEY='connection-acceptance-v1')


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True)
class ConnectionAcceptanceTests(ConnectionFixture, TestCase):
    def test_profile_list_is_scoped_without_secret_values_or_refs(self):
        response = self.client.get(self.path('profiles/'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['profiles'][0]['id'], 'org-a-v1')
        for value in ('fixture-private-secret','SCC_A_SECRET_V1','secret_key_env'):
            self.assertNotIn(value, response.content.decode())

    def test_connect_registers_immutable_target_without_calling_storage(self):
        with patch('botocore.httpsession.URLLib3Session.send', side_effect=AssertionError('Registration must not contact storage')):
            response = self.connect()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['connection']['state'], 'draft')
        self.assertEqual(response.json()['connection']['revision'], 1)
        self.assertNotIn('fixture-private-secret', response.content.decode())
        self.assertEqual(self.connect().json()['connection']['id'], response.json()['connection']['id'])

    def test_browser_cannot_supply_arbitrary_endpoint_or_secret(self):
        response = self.connect({'display_name':'Bad','slug':'bad','profile_id':'org-a-v1','reason':'Attempt unapproved endpoint','endpoint_url':'http://169.254.169.254/latest/meta-data'})
        self.assertEqual(response.status_code, 400)
        self.dns.assert_not_called()


class FakeS3:
    """S3 fixture tách khỏi SDK/network; chỉ có bytes kiểm thử."""
    def __init__(self):
        self.buckets = {'org-a-data':{'versioning':True,'tags':[], 'objects':{}, 'cors':[{
            'AllowedOrigins':['http://localhost:3000'],'AllowedMethods':['GET','HEAD','PUT'],
            'AllowedHeaders':['*'],'ExposeHeaders':['ETag']}]}}
        self.calls = []
        self.failure = None

    def _check(self,name,bucket):
        self.calls.append((name,bucket))
        if self.failure == name:
            raise ClientError({'Error':{'Code':'AccessDenied','Message':'Never expose fixture-private-secret or signed URLs'}},name)
        if bucket not in self.buckets:
            raise ClientError({'Error':{'Code':'NoSuchBucket','Message':'missing fixture'}},name)
        return self.buckets[bucket]

    def head_bucket(self,*,Bucket):
        self._check('HeadBucket',Bucket)
        return {}

    def get_bucket_versioning(self,*,Bucket):
        return {'Status':'Enabled' if self._check('GetBucketVersioning',Bucket)['versioning'] else 'Suspended'}

    def get_bucket_cors(self,*,Bucket):
        return {'CORSRules':self._check('GetBucketCors',Bucket)['cors']}

    def create_bucket(self,*,Bucket,**kwargs):
        assert Bucket.startswith('bluedrive-scc-') and Bucket not in self.buckets
        self.calls.append(('CreateBucket',Bucket))
        self.buckets[Bucket] = {'versioning':False,'tags':[],'objects':{},'cors':[]}
        return {}

    def put_bucket_tagging(self,*,Bucket,Tagging):
        self._check('PutBucketTagging',Bucket)['tags'] = Tagging['TagSet']

    def get_bucket_tagging(self,*,Bucket):
        return {'TagSet':self._check('GetBucketTagging',Bucket)['tags']}

    def put_bucket_versioning(self,*,Bucket,VersioningConfiguration):
        self._check('PutBucketVersioning',Bucket)['versioning'] = VersioningConfiguration['Status'] == 'Enabled'

    def put_bucket_cors(self,*,Bucket,CORSConfiguration):
        self._check('PutBucketCors',Bucket)['cors'] = CORSConfiguration['CORSRules']

    def put_object(self,*,Bucket,Key,Body,Metadata,**kwargs):
        target = self._check('PutObject',Bucket)
        assert target['versioning']
        version = 'fixture-version-' + str(len(target['objects'])+1)
        target['objects'][(Key,version)] = (bytes(Body),dict(Metadata))
        return {'VersionId':version,'ServerSideEncryption':kwargs.get('ServerSideEncryption','')}

    def get_object(self,*,Bucket,Key,VersionId):
        target = self._check('GetObject',Bucket)
        if (Key,VersionId) not in target['objects']:
            raise ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')
        body,metadata = target['objects'][(Key,VersionId)]
        return {'Body':io.BytesIO(body),'Metadata':metadata,'VersionId':VersionId}

    def get_paginator(self,name):
        assert name == 'list_object_versions'
        def pages(*,Bucket,Prefix):
            target = self._check('ListObjectVersions',Bucket)
            return [{'Versions':[{'Key':key,'VersionId':version} for key,version in target['objects'] if key.startswith(Prefix)]}]
        return SimpleNamespace(paginate=pages)

    def delete_object(self,*,Bucket,Key,VersionId):
        target = self._check('DeleteObject',Bucket)
        assert Bucket.startswith('bluedrive-scc-')
        target['objects'].pop((Key,VersionId),None)

    def delete_bucket(self,*,Bucket):
        target = self._check('DeleteBucket',Bucket)
        assert Bucket.startswith('bluedrive-scc-')
        if target['objects']:
            raise ClientError({'Error':{'Code':'BucketNotEmpty'}},'DeleteBucket')
        del self.buckets[Bucket]

    def close(self):
        pass


class WorkflowFixture(ConnectionFixture):
    def setUp(self):
        super().setUp()
        self.remote = FakeS3()
        self.enterContext(patch('infrastructure.connections.build_client',return_value=self.remote))
        self.enterContext(patch('infrastructure.connection_probes.build_client',return_value=self.remote))
        self.signer = Mock()
        self.signer.create_download_url.return_value = SimpleNamespace(url='https://objects-a.example.invalid/fixture?signature=mock-only')
        self.enterContext(patch('infrastructure.connection_probes.get_storage_adapter',return_value=self.signer))
        self.enterContext(patch('files.storage_adapters.get_storage_adapter',return_value=self.signer))

    def create_connection(self):
        response = self.connect()
        self.assertEqual(response.status_code,201,response.content)
        self.connection = StorageConnectionRevision.objects.get(pk=response.json()['connection']['id'])
        self.base = self.path(f'connections/{self.connection.pk}/',cluster=self.connection.cluster)
        return self.connection

    def read_check(self):
        response = self.client.post(self.base+'verify/',{'reason':'Read-only approved bucket check'},content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        return response

    def start(self):
        response = self.client.post(self.base+'probe/',{'reason':'Verify isolated LAB transfer','confirm_lab_fixture':True},content_type='application/json')
        self.assertEqual(response.status_code,201,response.content)
        self.probe = StorageConnectionProbe.objects.get(pk=response.json()['probe']['id'])
        self.probe_url = self.base+f'probes/{self.probe.pk}/'
        return response

    def digest(self):
        body = self.remote.buckets[self.probe.bucket]['objects'][(self.probe.object_key,self.probe.object_version_id)][0]
        return hashlib.sha256(body).hexdigest()

    def complete(self,digest=None):
        return self.client.post(self.probe_url+'complete/',{'sha256':digest or self.digest()},content_type='application/json')


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True,SECUREDRIVE_STORAGE_LAB_PROBES_ENABLED=True)
class ConnectionWorkflowTests(WorkflowFixture, TestCase):
    def test_head_success_does_not_activate_cluster_or_binding(self):
        self.create_connection()
        result = self.read_check()
        self.assertEqual(result.json()['connection']['state'],'read_verified')
        self.connection.cluster.refresh_from_db()
        self.assertEqual(self.connection.cluster.state,'draft')
        result = self.client.patch(self.path('binding/'),{'connection_id':str(self.connection.pk),'expected_generation':0,'reason':'Attempt early binding'},content_type='application/json')
        self.assertEqual(result.status_code,409)
        self.assertFalse(StorageBinding.objects.filter(state='active').exists())
        self.assertFalse(any(name == 'CreateBucket' for name,_ in self.remote.calls))

    def test_fixture_requires_flag_confirmation_and_lab_profile(self):
        self.create_connection()
        self.read_check()
        with override_settings(SECUREDRIVE_STORAGE_LAB_PROBES_ENABLED=False):
            response = self.client.post(self.base+'probe/',{'reason':'Disabled LAB fixture','confirm_lab_fixture':True},content_type='application/json')
            self.assertEqual(response.status_code,409)
        response = self.client.post(self.base+'probe/',{'reason':'Missing confirmation'},content_type='application/json')
        self.assertEqual(response.status_code,400)
        self.assertFalse(any(name == 'CreateBucket' for name,_ in self.remote.calls))

    def test_browser_checksum_and_owned_cleanup_are_required_before_ready(self):
        self.create_connection()
        self.read_check()
        result = self.start()
        self.assertNotIn('expected_sha256',result.content.decode())
        self.assertEqual(self.complete('0'*64).status_code,400)
        digest = self.digest()
        response = self.complete(digest)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['connection']['state'],'ready')
        self.assertNotIn(self.probe.bucket,self.remote.buckets)
        self.assertEqual(set(self.remote.buckets),{'org-a-data'})
        before = len(self.remote.calls)
        self.assertEqual(self.complete(digest).status_code,200)
        self.assertEqual(before,len(self.remote.calls))
        self.connection.cluster.refresh_from_db()
        self.assertEqual(self.connection.cluster.state,'ready')

    def test_cleanup_failure_keeps_ready_blocked_and_retry_recovers(self):
        self.create_connection()
        self.read_check()
        self.start()
        digest = self.digest()
        self.remote.failure = 'DeleteBucket'
        response = self.complete(digest)
        self.assertEqual(response.status_code,503)
        self.connection.refresh_from_db()
        self.assertNotEqual(self.connection.state,'ready')
        self.probe.refresh_from_db()
        self.assertEqual(self.probe.state,'cleanup_pending')
        self.remote.failure = None
        result = self.client.post(self.probe_url+'cleanup/',{},content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.state,'ready')

    def test_cleanup_never_deletes_unexpected_key_in_fixture_bucket(self):
        self.create_connection()
        self.read_check()
        self.start()
        self.remote.buckets[self.probe.bucket]['objects'][('unowned-data','unowned-version')] = (b'do not delete',{})
        result = self.complete()
        self.assertEqual(result.status_code,503)
        self.assertIn(('unowned-data','unowned-version'),self.remote.buckets[self.probe.bucket]['objects'])
        self.assertNotIn(('DeleteBucket','org-a-data'),self.remote.calls)

    def test_read_error_is_sanitized(self):
        self.create_connection()
        self.remote.failure = 'HeadBucket'
        response = self.client.post(self.base+'verify/',{'reason':'Read-only credential rejection'},content_type='application/json')
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json()['connection']['last_error_code'],'storage_identity_rejected')
        self.assertNotIn('fixture-private-secret',response.content.decode())

    def test_read_only_verification_does_not_change_bucket_policy(self):
        self.create_connection()
        self.read_check()
        self.assertEqual({name for name,_ in self.remote.calls},{'HeadBucket','GetBucketVersioning','GetBucketCors'})

    def test_connection_target_and_probe_ownership_are_immutable_in_db(self):
        self.create_connection()
        with self.assertRaises(IntegrityError),transaction.atomic():
            StorageConnectionRevision.objects.filter(pk=self.connection.pk).update(bucket='other-target')
        self.read_check()
        self.start()
        with self.assertRaises(IntegrityError),transaction.atomic():
            StorageConnectionProbe.objects.filter(pk=self.probe.pk).update(bucket='existing-data-bucket')

    def test_platform_default_checks_generation_and_never_routes_business_to_platform_storage(self):
        self.profiles['platform-v1'] = {**self.profiles['org-a-v1'],'scope':'platform','tenant_id':None}
        self.client.force_login(self.root)
        response = self.client.post(self.path('clusters/connect/',platform=True),{'display_name':'Platform LAB','slug':'platform-lab','profile_id':'platform-v1','reason':'Verify Platform default isolation'},content_type='application/json',HTTP_IDEMPOTENCY_KEY='platform-connection-fixture')
        self.assertEqual(response.status_code,201,response.content)
        self.connection = StorageConnectionRevision.objects.get(pk=response.json()['connection']['id'])
        self.base = self.path(f'connections/{self.connection.pk}/',cluster=self.connection.cluster,platform=True)
        self.read_check()
        self.start()
        self.assertEqual(self.complete().status_code,200)
        body = {'connection_id':str(self.connection.pk),'expected_generation':99,'reason':'Prepare Platform default after verification'}
        self.assertEqual(self.client.patch(self.path('binding/',platform=True),body,content_type='application/json').status_code,409)
        body['expected_generation'] = 0
        response = self.client.patch(self.path('binding/',platform=True),body,content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['binding']['generation'],1)
        replay = self.client.patch(self.path('binding/',platform=True),body,content_type='application/json')
        self.assertEqual(replay.status_code,200)
        self.assertTrue(replay.json()['unchanged'])
        with override_settings(SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=True):
            tenant = self.owner.personal_tenant
            target = upload_target(tenant,tenant.workspaces.get(is_default=True))
            self.assertEqual(target['storage_connection'].pk,self.connection.pk)
            self.assertEqual(target['storage_config'].tenant_id,tenant.pk)
            from accounts.models import Workspace
            space = Workspace.objects.create(tenant=self.tenant,name='Business isolation',slug='business-isolation',created_by=self.owner)
            with self.assertRaises(StorageConfigurationError):
                upload_target(self.tenant,space)
