"""Identity ứng dụng phải tự chứng minh chuyển bytes, không cần quyền quản trị bucket."""
import base64
import hashlib
import io
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError, ReadTimeoutError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from files.storage_adapters.s3_compatible import S3CompatibleStorageAdapter
from infrastructure.connection_probes import (RUNTIME_REQUIRED, cleanup_probe, complete_probe,
    reconcile_missing_lab_probe)
from infrastructure.connections import ConnectionRejected
from infrastructure.models import ClusterAuditEvent, StorageAccessGrant, StorageConnectionProbe
from infrastructure.test_connections import FakeS3, WorkflowFixture


class RuntimeS3(FakeS3):
    def __init__(self):
        super().__init__()
        self.uploads,self.sequence,self.forbid_admin = {},0,False
        self.ambiguous_init,self.lost_complete,self.null_version = False,False,False
        self.cross_bucket_code = 'AccessDenied'

    def _check(self,name,bucket):
        if self.forbid_admin and name in {'GetBucketVersioning','GetBucketCors','CreateBucket','PutBucketVersioning',
                'PutBucketCors','PutBucketTagging','GetBucketTagging','DeleteBucket'}:
            raise AssertionError('Runtime qualification must not administer buckets')
        return super()._check(name,bucket)

    def head_bucket(self,*,Bucket):
        if Bucket != 'org-a-data':
            self.calls.append(('HeadBucket',Bucket))
            raise ClientError({'Error':{'Code':self.cross_bucket_code}},'HeadBucket')
        return super().head_bucket(Bucket=Bucket)

    def put_object(self,*,Bucket,Key,Body,Metadata,**kwargs):
        target = self._check('PutObject',Bucket)
        self.sequence += 1
        version = 'null' if self.null_version else f'runtime-version-{self.sequence}'
        payload = Body.read() if hasattr(Body,'read') else bytes(Body)
        target['objects'][(Key,version)] = (payload,dict(Metadata))
        return {'VersionId':version,'ServerSideEncryption':'AES256'}

    def head_object(self,*,Bucket,Key,VersionId=None,**kwargs):
        target = self._check('HeadObject',Bucket)
        if VersionId is None:
            VersionId = next((version for key,version in reversed(target['objects']) if key == Key),None)
        if (Key,VersionId) not in target['objects']:
            raise ClientError({'Error':{'Code':'NoSuchKey'}},'HeadObject')
        payload,metadata = target['objects'][(Key,VersionId)]
        return {'VersionId':VersionId,'ContentLength':len(payload),'Metadata':dict(metadata),
            'ChecksumSHA256':base64.b64encode(hashlib.sha256(payload).digest()).decode(),'ChecksumType':'FULL_OBJECT',
            'ETag':'"'+hashlib.md5(payload).hexdigest()+'"','ServerSideEncryption':'AES256'}

    def get_object(self,*,Bucket,Key,VersionId):
        self._check('GetObject',Bucket)
        result = self.head_object(Bucket=Bucket,Key=Key,VersionId=VersionId)
        result['Body'] = io.BytesIO(self.buckets[Bucket]['objects'][(Key,VersionId)][0])
        return result

    def create_multipart_upload(self,*,Bucket,Key,Metadata,**kwargs):
        self._check('CreateMultipartUpload',Bucket)
        identity = uuid.uuid4().hex
        self.uploads[identity] = {'bucket':Bucket,'key':Key,'metadata':dict(Metadata),'parts':{}}
        if self.ambiguous_init:
            raise ReadTimeoutError(endpoint_url='https://objects.example.invalid',error='response lost')
        return {'UploadId':identity}

    def _upload(self,Bucket,Key,UploadId,name):
        self._check(name,Bucket)
        record = self.uploads.get(UploadId)
        if not record or (record['bucket'],record['key']) != (Bucket,Key):
            raise ClientError({'Error':{'Code':'NoSuchUpload'}},name)
        return record

    def upload_part(self,*,Bucket,Key,UploadId,PartNumber,Body):
        record = self._upload(Bucket,Key,UploadId,'UploadPart')
        payload = bytes(Body)
        etag = '"'+hashlib.md5(payload).hexdigest()+'"'
        record['parts'][PartNumber] = (payload,etag)
        return {'ETag':etag}

    def list_parts(self,*,Bucket,Key,UploadId,**kwargs):
        record = self._upload(Bucket,Key,UploadId,'ListParts')
        return {'Parts':[{'PartNumber':number,'Size':len(payload),'ETag':etag}
            for number,(payload,etag) in sorted(record['parts'].items())]}

    def complete_multipart_upload(self,*,Bucket,Key,UploadId,MultipartUpload):
        record = self._upload(Bucket,Key,UploadId,'CompleteMultipartUpload')
        payload = b''.join(record['parts'][item['PartNumber']][0] for item in MultipartUpload['Parts'])
        result = self.put_object(Bucket=Bucket,Key=Key,Body=payload,Metadata=record['metadata'])
        del self.uploads[UploadId]
        if self.lost_complete:
            raise ReadTimeoutError(endpoint_url='https://objects.example.invalid',error='response lost')
        return result

    def abort_multipart_upload(self,*,Bucket,Key,UploadId):
        self._upload(Bucket,Key,UploadId,'AbortMultipartUpload')
        del self.uploads[UploadId]
        return {}

    def delete_object(self,*,Bucket,Key,VersionId):
        target = self._check('DeleteObject',Bucket)
        self.calls.append(('ExactDelete',Key,VersionId))
        target['objects'].pop((Key,VersionId),None)

    def generate_presigned_url(self,operation,*,Params,ExpiresIn,HttpMethod):
        query = {'versionId':Params['VersionId']} if operation == 'get_object' else {
            'uploadId':Params['UploadId'],'partNumber':Params['PartNumber']}
        return 'https://objects-a.example.invalid/'+Params['Bucket']+'/'+Params['Key']+'?'+urlencode(query)


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True,
    SECUREDRIVE_STORAGE_RUNTIME_PROBES_ENABLED=True,SECUREDRIVE_STORAGE_LAB_PROBES_ENABLED=False)
class RuntimeQualificationTests(WorkflowFixture,TestCase):
    def setUp(self):
        super().setUp()
        self.profiles['org-a-v1']['lab'] = False
        self.remote = RuntimeS3()
        self.enterContext(patch('infrastructure.connections.build_client',return_value=self.remote))
        self.enterContext(patch('infrastructure.connection_probes.build_client',return_value=self.remote))
        self.adapter = S3CompatibleStorageAdapter(endpoint_url='https://objects-a.example.invalid',bucket='org-a-data',
            client=self.remote,max_attempts=1)
        self.enterContext(patch('infrastructure.connection_probes.get_storage_adapter',return_value=self.adapter))
        self.create_connection()
        self.read_check()
        self.remote.calls.clear()
        self.remote.forbid_admin = True

    def runtime_start(self,**extra):
        response = self.client.post(self.base+'probe/',{'mode':'runtime','reason':'Qualify app identity transfer',
            'confirm_runtime_fixture':True,**extra},content_type='application/json')
        if response.status_code == 201:
            self.probe = StorageConnectionProbe.objects.get(pk=response.json()['probe']['id'])
            self.probe_url = self.base+f'probes/{self.probe.pk}/'
        return response

    def browser_receipts(self,response,*,payload=None):
        upload = response.json()['upload_authorization']
        query = parse_qs(urlsplit(upload['url']).query)
        payload = base64.b64decode(upload['body_base64']) if payload is None else payload
        key = urlsplit(upload['url']).path.split('/org-a-data/',1)[1]
        receipt = self.remote.upload_part(Bucket=self.probe.bucket,Key=key,UploadId=query['uploadId'][0],PartNumber=1,Body=payload)
        source = self.remote.buckets[self.probe.bucket]['objects'][(self.probe.object_key,self.probe.object_version_id)][0]
        return {'sha256':hashlib.sha256(source).hexdigest(),'put_sha256':hashlib.sha256(base64.b64decode(upload['body_base64'])).hexdigest(),
            'put_etag':receipt['ETag']}

    def runtime_complete(self,receipts):
        return self.client.post(self.probe_url+'complete/',receipts,content_type='application/json')

    def test_runtime_identity_without_bucket_admin_completes_all_required_proofs(self):
        response = self.runtime_start()
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(response.json()['probe']['mode'],'runtime')
        self.assertNotIn('expected_sha256',response.content.decode())
        self.assertNotIn('browser_expected_sha256',response.content.decode())
        result = self.runtime_complete(self.browser_receipts(response))
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()['connection']['state'],'ready')
        self.assertEqual(result.json()['connection']['verification_scope'],'runtime')
        self.probe.refresh_from_db()
        self.assertTrue(all(self.probe.checks.get(key) is True for key in RUNTIME_REQUIRED))
        self.assertEqual(self.remote.buckets['org-a-data']['objects'],{})
        self.assertEqual(self.remote.uploads,{})
        calls = len(self.remote.calls)
        self.assertEqual(self.runtime_complete(self.browser_receipts_cached).status_code,200) if hasattr(self,'browser_receipts_cached') else None
        self.assertIn('org-a-data',self.remote.buckets)

    def test_runtime_flag_and_explicit_confirmation_are_required(self):
        with override_settings(SECUREDRIVE_STORAGE_RUNTIME_PROBES_ENABLED=False):
            self.assertEqual(self.runtime_start().status_code,409)
        self.assertEqual(self.runtime_start(bucket='another-bucket').status_code,400)
        self.assertEqual(self.runtime_start(confirm_runtime_fixture=False).status_code,400)
        self.assertEqual(self.remote.calls,[])

    def test_required_put_denial_cannot_be_ready_and_failed_probe_can_retry(self):
        self.remote.failure = 'PutObject'
        self.assertEqual(self.runtime_start().status_code,503)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.state,'failed')
        self.remote.failure = None
        response = self.runtime_start()
        self.assertEqual(response.status_code,201,response.content)

    def test_cross_bucket_not_found_does_not_substitute_for_access_denied(self):
        self.remote.cross_bucket_code = 'NoSuchBucket'
        result = self.runtime_start()
        self.assertEqual(result.status_code,503,result.content)
        self.connection.refresh_from_db()
        self.assertNotEqual(self.connection.state,'ready')

    def test_cleanup_failure_stays_pending_and_retry_requires_all_browser_proofs(self):
        response = self.runtime_start()
        self.assertEqual(response.status_code,201,response.content)
        receipts = self.browser_receipts(response)
        self.remote.failure = 'DeleteObject'
        result = self.runtime_complete(receipts)
        self.assertEqual(result.status_code,503,result.content)
        self.probe.refresh_from_db()
        self.connection.refresh_from_db()
        self.assertEqual((self.probe.state,self.connection.state),('cleanup_pending','failed'))
        self.remote.failure = None
        result = self.client.post(self.probe_url+'cleanup/',{},content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.state,'ready')

    def test_wrong_browser_body_is_not_accepted_from_client_digest_alone(self):
        response = self.runtime_start()
        result = self.runtime_complete(self.browser_receipts(response,payload=b'x'*64))
        self.assertEqual(result.status_code,503,result.content)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.state,'failed')
        self.assertEqual(self.remote.buckets['org-a-data']['objects'],{})

    def test_missing_required_receipt_cannot_promote_connection(self):
        response = self.runtime_start()
        checks = dict(self.probe.checks)
        checks.pop('server_head')
        StorageConnectionProbe.objects.filter(pk=self.probe.pk).update(checks=checks)
        result = self.runtime_complete(self.browser_receipts(response))
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()['probe']['state'],'failed')
        self.assertNotEqual(result.json()['connection']['state'],'ready')

    def test_cleanup_preserves_object_with_wrong_ownership_metadata(self):
        response = self.runtime_start()
        receipts = self.browser_receipts(response)
        key = (self.probe.object_key,self.probe.object_version_id)
        payload,_ = self.remote.buckets[self.probe.bucket]['objects'][key]
        self.remote.buckets[self.probe.bucket]['objects'][key] = (payload,{'foreign-owner':'keep'})
        result = self.runtime_complete(receipts)
        self.assertEqual(result.status_code,503,result.content)
        self.assertIn(key,self.remote.buckets[self.probe.bucket]['objects'])
        self.assertFalse(any(call[0]=='ExactDelete' and call[1]==self.probe.object_key for call in self.remote.calls))

    def test_ambiguous_multipart_creation_stays_pending_without_blind_cleanup_or_retry(self):
        self.remote.ambiguous_init = True
        result = self.runtime_start()
        self.assertEqual(result.status_code,503,result.content)
        probe = self.connection.probes.get()
        self.assertEqual(probe.state,'cleanup_pending')
        self.assertEqual(len(self.remote.uploads),1)
        self.assertEqual(self.runtime_start().status_code,409)

    def test_mode_bucket_and_root_key_are_database_guarded(self):
        response = self.runtime_start()
        self.assertEqual(response.status_code,201,response.content)
        for field,value in (('mode','lab'),('bucket','another-data-bucket'),('object_key','staging/'+uuid.uuid4().hex),('bucket_created',True)):
            with self.subTest(field=field),self.assertRaises(IntegrityError),transaction.atomic():
                StorageConnectionProbe.objects.filter(pk=self.probe.pk).update(**{field:value})

    def test_revoked_actor_cannot_complete_or_promote_during_background_cleanup(self):
        response = self.runtime_start()
        receipts = self.browser_receipts(response)
        StorageAccessGrant.objects.filter(membership=self.owner_member,permission='storage.configure').delete()
        with self.assertRaises(ConnectionRejected):
            complete_probe(self.probe,self.owner,receipts['sha256'],put_digest=receipts['put_sha256'],put_etag=receipts['put_etag'])
        result = cleanup_probe(self.probe)
        self.assertEqual(result.state,'failed')
        self.connection.refresh_from_db()
        self.assertNotEqual(self.connection.state,'ready')

    def test_null_version_never_qualifies_runtime(self):
        self.remote.null_version = True
        self.assertEqual(self.runtime_start().status_code,503)
        self.connection.refresh_from_db()
        self.assertNotEqual(self.connection.state,'ready')

    def test_lost_completion_response_is_reconciled_without_replaying_browser_upload(self):
        response = self.runtime_start()
        receipts = self.browser_receipts(response)
        self.remote.lost_complete = True
        result = self.runtime_complete(receipts)
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()['connection']['state'],'ready')
        self.assertEqual(sum(call[0]=='CompleteMultipartUpload' for call in self.remote.calls),1)

    def test_operator_absence_reconciliation_closes_only_old_uncreated_lab_history(self):
        identity = uuid.uuid4()
        probe = StorageConnectionProbe.objects.create(id=identity,connection=self.connection,generation=1,
            bucket='bluedrive-scc-'+identity.hex,object_key='staging/'+identity.hex,expected_sha256='a'*64,
            browser_origin='http://localhost:3000',state='cleanup_pending',expires_at=timezone.now()-timedelta(minutes=1),
            created_by=self.owner,reason='Recover old rejected LAB probe')
        operator = Mock()
        operator.head_bucket.side_effect = ClientError({'Error':{'Code':'AccessDenied'}},'HeadBucket')
        with self.assertRaises(ConnectionRejected):
            reconcile_missing_lab_probe(probe,self.owner,'Confirm missing LAB fixture',operator)
        operator.head_bucket.side_effect = ClientError({'Error':{'Code':'NoSuchBucket'}},'HeadBucket')
        result = reconcile_missing_lab_probe(probe,self.owner,'Operator checked bucket absence',operator)
        self.assertEqual(result.state,'failed')
        self.connection.refresh_from_db()
        self.assertNotEqual(self.connection.state,'ready')
        self.assertTrue(ClusterAuditEvent.objects.filter(resource_ref=str(probe.pk),action='storage.connection.fixture_absence_reconciled').exists())
        operator.delete_bucket.assert_not_called()
