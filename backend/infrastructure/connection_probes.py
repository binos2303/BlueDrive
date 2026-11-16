"""Tách provisioning LAB khỏi fixture runtime giới hạn trong bucket ứng dụng đã duyệt."""
import base64
import hashlib
import hmac
import io
import secrets
import uuid
from datetime import timedelta

from botocore.exceptions import ClientError
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from files.storage_adapters import get_storage_adapter
from files.storage_adapters.base import MultipartPart
from infrastructure.connection_profiles import build_client
from infrastructure.connections import ConnectionRejected, error_code, inspect_read_only, reason_text, require_configure
from infrastructure.models import ClusterAuditEvent, StorageCluster, StorageConnectionProbe, StorageConnectionRevision


def _missing(error):
    return isinstance(error,ClientError) and (
        error.response.get('Error',{}).get('Code') == 'NoSuchBucket'
        or (getattr(error,'operation_name','') in {'HeadBucket','DeleteBucket'} and error.response.get('Error',{}).get('Code') in {'404','NotFound'}))


def _read_fixture(client,probe,version):
    response = client.get_object(Bucket=probe.bucket,Key=probe.object_key,VersionId=version)
    stream = response['Body']
    try:
        content = stream.read(65)
    finally:
        stream.close()
    if len(content) != 64 or hashlib.sha256(content).hexdigest() != probe.expected_sha256 or response.get('Metadata',{}).get('bluedrive-probe-id') != str(probe.pk):
        raise ConnectionRejected('fixture_integrity_failed')
    return True


def cleanup_fixture(probe,client):
    if probe.mode == 'runtime':
        return _cleanup_runtime_fixture(probe,client)
    if probe.bucket != 'bluedrive-scc-' + probe.pk.hex or probe.object_key != 'staging/' + probe.pk.hex:
        raise ConnectionRejected('fixture_ownership_unconfirmed')
    if not probe.bucket_created:
        try:
            client.head_bucket(Bucket=probe.bucket)
        except ClientError as error:
            if _missing(error):
                return True
            raise
        raise ConnectionRejected('fixture_ownership_unconfirmed')
    try:
        try:
            tags = client.get_bucket_tagging(Bucket=probe.bucket).get('TagSet',[])
            owned = any(tag.get('Key') == 'bluedrive-probe-id' and tag.get('Value') == str(probe.pk) for tag in tags)
        except ClientError as error:
            if _missing(error):
                return True
            owned = False
        if not owned:
            # DeleteBucket chỉ thành công với bucket rỗng; không xóa object thiếu bằng chứng.
            client.delete_bucket(Bucket=probe.bucket)
            return True
        pages = client.get_paginator('list_object_versions').paginate(Bucket=probe.bucket,Prefix=probe.object_key)
        count = 0
        for page in pages:
            for record in page.get('Versions',[]):
                if record.get('Key') != probe.object_key:
                    continue
                count += 1
                if count > 100:
                    raise ConnectionRejected('fixture_cleanup_limit')
                version = record.get('VersionId')
                if not version:
                    raise ConnectionRejected('fixture_version_unavailable')
                if version != probe.object_version_id:
                    _read_fixture(client,probe,version)
                client.delete_object(Bucket=probe.bucket,Key=probe.object_key,VersionId=version)
            for record in page.get('DeleteMarkers',[]):
                if record.get('Key') == probe.object_key:
                    count += 1
                    if count > 100 or not record.get('VersionId'):
                        raise ConnectionRejected('fixture_cleanup_limit')
                    client.delete_object(Bucket=probe.bucket,Key=probe.object_key,VersionId=record['VersionId'])
        client.delete_bucket(Bucket=probe.bucket)
        return True
    except ClientError as error:
        if _missing(error):
            return True
        raise


def _probe_gate(connection):
    if not settings.SECUREDRIVE_STORAGE_LAB_PROBES_ENABLED or not connection.lab:
        raise ConnectionRejected('lab_fixture_probe_not_enabled')


def begin_probe(connection,actor,reason,browser_origin,*,mode='lab'):
    if mode == 'runtime':
        return _begin_runtime_probe(connection,actor,reason,browser_origin)
    if mode != 'lab':
        raise ConnectionRejected('fixture_mode_invalid',400)
    reason = reason_text(reason)
    _probe_gate(connection)
    payload = secrets.token_bytes(64)
    identity = uuid.uuid4()
    with transaction.atomic():
        require_configure(actor,connection.cluster.tenant_id,lock=True)
        current = StorageConnectionRevision.objects.select_for_update().get(pk=connection.pk)
        if current.state not in ('read_verified','ready') or current.probes.filter(state__in=['creating','awaiting_browser','cleaning','cleanup_pending']).exists():
            raise ConnectionRejected('connection_not_ready_for_fixture')
        previously_ready = current.state == 'ready'
        current.verification_generation += 1
        if not previously_ready:
            current.state = 'verifying'
        current.save(update_fields=['verification_generation','state'])
        probe = StorageConnectionProbe.objects.create(id=identity,connection=current,generation=current.verification_generation,
            bucket='bluedrive-scc-' + identity.hex,object_key='staging/' + identity.hex,
            expected_sha256=hashlib.sha256(payload).hexdigest(),browser_origin=browser_origin,
            expires_at=timezone.now()+timedelta(minutes=5),created_by=actor,reason=reason,
            checks={'previously_ready':previously_ready})
    client = None
    try:
        client = build_client(current)
        checks = inspect_read_only(client,current,browser_origin)
        if not checks['versioning'] or not checks['cors']:
            raise ConnectionRejected('bucket_browser_policy_incomplete')
        params = {'Bucket':probe.bucket}
        if current.region != 'us-east-1':
            params['CreateBucketConfiguration'] = {'LocationConstraint':current.region}
        client.create_bucket(**params)
        probe.bucket_created = True
        if not StorageConnectionProbe.objects.filter(pk=probe.pk,state='creating').update(bucket_created=True):
            raise ConnectionRejected('fixture_probe_superseded')
        client.put_bucket_tagging(Bucket=probe.bucket,Tagging={'TagSet':[{'Key':'bluedrive-probe-id','Value':str(probe.pk)}]})
        client.put_bucket_versioning(Bucket=probe.bucket,VersioningConfiguration={'Status':'Enabled'})
        client.put_bucket_cors(Bucket=probe.bucket,CORSConfiguration={'CORSRules':[{
            'AllowedOrigins':[browser_origin],'AllowedMethods':['GET','HEAD'],'AllowedHeaders':['*'],
            'ExposeHeaders':['ETag','x-amz-version-id'],'MaxAgeSeconds':300}]})
        encryption = {'ServerSideEncryption':current.server_side_encryption} if current.server_side_encryption else {}
        if current.server_side_encryption == 'aws:kms':
            encryption['SSEKMSKeyId'] = current.kms_key_id
        stored = client.put_object(Bucket=probe.bucket,Key=probe.object_key,Body=payload,
            Metadata={'bluedrive-probe-id':str(probe.pk)},**encryption)
        version = stored.get('VersionId','')
        if not version or version == 'null':
            raise ConnectionRejected('fixture_version_unavailable')
        probe.object_version_id = version
        if current.server_side_encryption and stored.get('ServerSideEncryption') != current.server_side_encryption:
            raise ConnectionRejected('fixture_sse_not_confirmed')
        _read_fixture(client,probe,version)
        checks.update({'server_sha256':True,'version_pinned':True,'sse_response':bool(current.server_side_encryption),'previously_ready':previously_ready})
        with transaction.atomic():
            locked = StorageConnectionProbe.objects.select_for_update().get(pk=probe.pk)
            if locked.state != 'creating':
                raise ConnectionRejected('fixture_probe_superseded')
            locked.state,locked.object_version_id,locked.checks = 'awaiting_browser',version,checks
            locked.save(update_fields=['state','object_version_id','checks'])
        signed = get_storage_adapter(connection=current,bucket=probe.bucket).create_download_url(probe.object_key,
            version_id=version,download_name='storage-verification.bin',expires_in=180)
        probe.refresh_from_db()
        return probe,signed.url
    except Exception as error:
        code = error.code if isinstance(error,ConnectionRejected) else error_code(error)
        cleaned = False
        if client is not None:
            try:
                cleaned = cleanup_fixture(probe,client)
            except Exception:
                pass
        with transaction.atomic():
            changed = StorageConnectionProbe.objects.filter(pk=probe.pk,state__in=['creating','awaiting_browser'],cleanup_generation=0).update(state='failed' if cleaned else 'cleanup_pending',
                bucket_created=probe.bucket_created,object_version_id=probe.object_version_id,error_code=code,
                completed_at=timezone.now() if cleaned else None)
            if changed:
                StorageConnectionRevision.objects.filter(pk=current.pk,verification_generation=probe.generation).update(
                    state='ready' if previously_ready else 'failed',last_error_code=code)
        raise ConnectionRejected(code,503) from None
    finally:
        if client is not None:
            client.close()


def complete_probe(probe,actor,digest,*,put_digest=None,put_etag=None):
    if probe.mode == 'runtime':
        return _complete_runtime_probe(probe,actor,digest,put_digest,put_etag)
    if not isinstance(digest,str) or len(digest) != 64 or not hmac.compare_digest(digest,probe.expected_sha256):
        raise ConnectionRejected('browser_fixture_digest_mismatch',400)
    with transaction.atomic():
        current = StorageConnectionProbe.objects.select_for_update().select_related('connection').get(pk=probe.pk)
        if current.state == 'succeeded':
            return current
        if current.state != 'awaiting_browser' or current.expires_at <= timezone.now():
            raise ConnectionRejected('fixture_probe_expired_or_busy')
        current.state = 'cleaning'
        current.cleanup_generation += 1
        current.checks = {**current.checks,'browser_sha256':True}
        current.save(update_fields=['state','checks','cleanup_generation'])
    return finish_cleanup(current,actor,browser_verified=True)


def finish_cleanup(probe,actor=None,*,browser_verified=False):
    client = None
    try:
        client = build_client(probe.connection)
        cleanup_fixture(probe,client)
    except Exception as error:
        StorageConnectionProbe.objects.filter(pk=probe.pk,state='cleaning',cleanup_generation=probe.cleanup_generation).update(state='cleanup_pending',error_code='fixture_cleanup_pending')
        if probe.mode == 'runtime':
            StorageConnectionRevision.objects.filter(pk=probe.connection_id,verification_generation=probe.generation).update(
                state='failed',last_error_code='fixture_cleanup_pending')
        raise ConnectionRejected('fixture_cleanup_pending',503) from None
    finally:
        if client is not None:
            client.close()
    with transaction.atomic():
        authorized = True
        try:
            require_configure(actor or probe.created_by,probe.connection.cluster.tenant_id,lock=True)
        except ConnectionRejected:
            authorized = False
        current = StorageConnectionRevision.objects.select_for_update().get(pk=probe.connection_id)
        locked = StorageConnectionProbe.objects.select_for_update().get(pk=probe.pk)
        if locked.state != 'cleaning' or locked.cleanup_generation != probe.cleanup_generation:
            raise ConnectionRejected('fixture_probe_superseded')
        required = RUNTIME_REQUIRED if locked.mode == 'runtime' else ('head_bucket','versioning','cors','server_sha256','version_pinned')
        ready = authorized and browser_verified and all(locked.checks.get(key) is True for key in required) and current.verification_generation == probe.generation and probe.expires_at > timezone.now()
        locked.state = 'succeeded' if ready else 'expired' if probe.expires_at <= timezone.now() else 'failed'
        locked.completed_at = timezone.now()
        locked.checks = {**locked.checks,'browser_sha256':browser_verified,'cleanup':True}
        locked.error_code = '' if ready else locked.error_code
        locked.save(update_fields=['state','completed_at','checks','error_code'])
        if current.verification_generation == probe.generation:
            if ready:
                current.state,current.verified_at,current.last_error_code = 'ready',timezone.now(),''
                StorageCluster.objects.filter(pk=current.cluster_id).update(state='ready',verified_at=current.verified_at)
            elif locked.mode == 'runtime' or not probe.checks.get('previously_ready'):
                current.state,current.last_error_code = 'failed','fixture_verification_incomplete'
            current.save(update_fields=['state','verified_at','last_error_code'])
        ClusterAuditEvent.objects.create(cluster=current.cluster,actor=actor,action='storage.connection.fixture_checked',
            resource_ref=str(probe.pk),after={'state':locked.state,'revision':current.revision},reason=probe.reason)
        return locked


def cleanup_probe(probe,actor=None,*,recover_expired=False):
    with transaction.atomic():
        if actor is not None:
            require_configure(actor,probe.connection.cluster.tenant_id,lock=True)
        current = StorageConnectionProbe.objects.select_for_update().select_related('connection').get(pk=probe.pk)
        if current.state in ('succeeded','failed','expired'):
            return current
        if current.state == 'cleaning' and not (recover_expired and current.expires_at <= timezone.now()):
            raise ConnectionRejected('fixture_cleanup_busy')
        current.state = 'cleaning'
        current.cleanup_generation += 1
        current.save(update_fields=['state','cleanup_generation'])
    return finish_cleanup(current,actor,browser_verified=current.checks.get('browser_sha256') is True)


RUNTIME_REQUIRED = ('head_bucket','server_put','server_head','server_sha256','metadata','version_pinned',
    'multipart','multipart_abort','cross_bucket_denied','presigned_put','presigned_get','browser_put_sha256','delete_verified')


def _runtime_key(probe,role):
    return probe.object_key if role == 'server' else 'staging/' + uuid.uuid5(probe.pk,role).hex


def _object_missing(error):
    return isinstance(error,ClientError) and error.response.get('Error',{}).get('Code') in {'NoSuchKey','NoSuchVersion','404','NotFound'}


def _save_runtime(probe,**updates):
    probe.checks = {**probe.checks,**updates}
    changed = StorageConnectionProbe.objects.filter(pk=probe.pk,state__in=['creating','awaiting_browser','cleaning'],
        cleanup_generation=probe.cleanup_generation).update(checks=probe.checks)
    if not changed:
        raise ConnectionRejected('fixture_probe_superseded')


def _runtime_receipt(probe,role,version):
    objects = {**probe.checks.get('objects',{}),role:{'key':_runtime_key(probe,role),'version':version}}
    _save_runtime(probe,objects=objects)


def _runtime_read(client,probe,role,version,expected_sha):
    params = {'Bucket':probe.bucket,'Key':_runtime_key(probe,role),'VersionId':version}
    head = client.head_object(**params)
    if (head.get('VersionId') != version or head.get('ContentLength') != 64
            or head.get('Metadata',{}).get('bluedrive-probe-id') != str(probe.pk)
            or head.get('Metadata',{}).get('securedrive-sha256') != expected_sha):
        raise ConnectionRejected('fixture_integrity_failed')
    if probe.connection.server_side_encryption and head.get('ServerSideEncryption') != probe.connection.server_side_encryption:
        raise ConnectionRejected('fixture_sse_not_confirmed')
    response = client.get_object(**params)
    stream = response['Body']
    try:
        payload = stream.read(65)
    finally:
        stream.close()
    if (response.get('VersionId') != version or len(payload) != 64 or hashlib.sha256(payload).hexdigest() != expected_sha
            or response.get('Metadata',{}).get('bluedrive-probe-id') != str(probe.pk)):
        raise ConnectionRejected('fixture_integrity_failed')


def _runtime_multipart(probe,client,role,sha256):
    uploads = {**probe.checks.get('uploads',{}),role:{'started':True,'id':'','done':False}}
    _save_runtime(probe,uploads=uploads)
    try:
        result = client.create_multipart_upload(Bucket=probe.bucket,Key=_runtime_key(probe,role),
            Metadata={'bluedrive-probe-id':str(probe.pk),'securedrive-upload-id':str(probe.pk),'securedrive-sha256':sha256},
            ContentType='application/octet-stream',**({'ServerSideEncryption':probe.connection.server_side_encryption,
                **({'SSEKMSKeyId':probe.connection.kms_key_id} if probe.connection.server_side_encryption == 'aws:kms' else {})}
                if probe.connection.server_side_encryption else {}))
    except ClientError as error:
        if error.response.get('Error',{}).get('Code') in {'AccessDenied','403','InvalidAccessKeyId','SignatureDoesNotMatch'}:
            uploads[role]['started'] = False
            _save_runtime(probe,uploads=uploads)
        raise
    identity = result.get('UploadId')
    if not isinstance(identity,str) or not identity:
        raise ConnectionRejected('fixture_multipart_receipt_missing')
    uploads[role]['id'] = identity
    _save_runtime(probe,uploads=uploads)
    return identity


def _abort_runtime_upload(probe,client,role,upload):
    params = {'Bucket':probe.bucket,'Key':_runtime_key(probe,role),'UploadId':upload}
    try:
        client.abort_multipart_upload(**params)
    except ClientError as error:
        if error.response.get('Error',{}).get('Code') != 'NoSuchUpload':
            raise
    try:
        client.list_parts(**params)
    except ClientError as error:
        if error.response.get('Error',{}).get('Code') == 'NoSuchUpload':
            return
        raise
    raise ConnectionRejected('fixture_multipart_abort_unconfirmed')


def runtime_authorizations(probe,*,expires_in=180):
    adapter = get_storage_adapter(connection=probe.connection)
    download = adapter.create_download_url(probe.object_key,version_id=probe.object_version_id,
        download_name='storage-verification.bin',expires_in=expires_in)
    upload = adapter.create_part_upload_url(_runtime_key(probe,'browser'),probe.checks['uploads']['browser']['id'],1,expires_in=expires_in)
    return {'authorization':{'url':download.url,'expires_in':expires_in},
        'upload_authorization':{'url':upload.url,'method':upload.method,'headers':upload.required_headers,
            'body_base64':probe.checks['browser_payload'],'expires_in':expires_in}}


def _begin_runtime_probe(connection,actor,reason,browser_origin):
    reason = reason_text(reason)
    if not getattr(settings,'SECUREDRIVE_STORAGE_RUNTIME_PROBES_ENABLED',False):
        raise ConnectionRejected('runtime_fixture_probe_not_enabled')
    payload,browser_payload,identity = secrets.token_bytes(64),secrets.token_bytes(64),uuid.uuid4()
    with transaction.atomic():
        require_configure(actor,connection.cluster.tenant_id,lock=True)
        current = StorageConnectionRevision.objects.select_for_update().get(pk=connection.pk)
        if (current.state not in ('read_verified','ready','failed') or not current.read_verified_at
                or current.probes.filter(state__in=['creating','awaiting_browser','cleaning','cleanup_pending']).exists()):
            raise ConnectionRejected('connection_not_ready_for_fixture')
        previously_ready = current.state == 'ready'
        current.verification_generation += 1
        current.state,current.last_error_code = 'verifying',''
        current.save(update_fields=['verification_generation','state','last_error_code'])
        probe = StorageConnectionProbe.objects.create(id=identity,mode='runtime',connection=current,
            generation=current.verification_generation,bucket=current.bucket,object_key='staging/'+identity.hex,
            expected_sha256=hashlib.sha256(payload).hexdigest(),browser_origin=browser_origin,
            expires_at=timezone.now()+timedelta(minutes=5),created_by=actor,reason=reason,
            checks={'previously_ready':previously_ready,'objects':{},'uploads':{},
                'browser_payload':base64.b64encode(browser_payload).decode(),
                'browser_expected_sha256':hashlib.sha256(browser_payload).hexdigest(),'server_write_started':True})
    client = None
    try:
        client = build_client(current)
        client.head_bucket(Bucket=current.bucket)
        _save_runtime(probe,head_bucket=True)
        adapter = get_storage_adapter(connection=current)
        stat = adapter.put_object(probe.object_key,io.BytesIO(payload),size_bytes=64,sha256_hex=probe.expected_sha256,
            metadata={'bluedrive-probe-id':str(probe.pk)})
        probe.object_version_id = stat.version_id or 'null'
        _runtime_receipt(probe,'server',probe.object_version_id)
        StorageConnectionProbe.objects.filter(pk=probe.pk,state='creating').update(object_version_id=probe.object_version_id)
        if not stat.version_id or stat.version_id == 'null':
            raise ConnectionRejected('fixture_version_unavailable')
        _runtime_read(client,probe,'server',stat.version_id,probe.expected_sha256)
        _save_runtime(probe,server_put=True,server_head=True,server_sha256=True,metadata=True,version_pinned=True)
        try:
            client.head_bucket(Bucket='bluedrive-deny-'+probe.pk.hex)
        except ClientError as error:
            if error.response.get('Error',{}).get('Code') not in {'AccessDenied','403'}:
                raise ConnectionRejected('cross_bucket_deny_unconfirmed') from None
        else:
            raise ConnectionRejected('cross_bucket_deny_unconfirmed')
        _save_runtime(probe,cross_bucket_denied=True)
        abort_id = _runtime_multipart(probe,client,'abort',probe.expected_sha256)
        _abort_runtime_upload(probe,client,'abort',abort_id)
        _save_runtime(probe,multipart_abort=True)
        _runtime_multipart(probe,client,'browser',probe.checks['browser_expected_sha256'])
        changed = StorageConnectionProbe.objects.filter(pk=probe.pk,state='creating',cleanup_generation=0).update(state='awaiting_browser')
        if not changed:
            raise ConnectionRejected('fixture_probe_superseded')
        probe.refresh_from_db()
        return probe,runtime_authorizations(probe)['authorization']['url']
    except Exception as error:
        code = error.code if isinstance(error,ConnectionRejected) else error_code(error)
        cleaned = False
        if client is not None:
            try:
                cleaned = cleanup_fixture(probe,client)
            except Exception:
                pass
        StorageConnectionProbe.objects.filter(pk=probe.pk,state__in=['creating','awaiting_browser'],cleanup_generation=0).update(
            state='failed' if cleaned else 'cleanup_pending',error_code=code,completed_at=timezone.now() if cleaned else None)
        StorageConnectionRevision.objects.filter(pk=current.pk,verification_generation=probe.generation).update(state='failed',last_error_code=code)
        raise ConnectionRejected(code,503) from None
    finally:
        if client is not None:
            client.close()


def _complete_runtime_probe(probe,actor,digest,put_digest,put_etag):
    if (not isinstance(digest,str) or not hmac.compare_digest(digest,probe.expected_sha256)
            or not isinstance(put_digest,str) or not hmac.compare_digest(put_digest,probe.checks.get('browser_expected_sha256',''))
            or not isinstance(put_etag,str) or not 1 <= len(put_etag) <= 256 or '\r' in put_etag or '\n' in put_etag):
        raise ConnectionRejected('browser_fixture_digest_mismatch',400)
    with transaction.atomic():
        require_configure(actor,probe.connection.cluster.tenant_id,lock=True)
        current = StorageConnectionProbe.objects.select_for_update().select_related('connection__cluster').get(pk=probe.pk)
        if current.state == 'succeeded':
            return current
        if current.state != 'awaiting_browser' or current.expires_at <= timezone.now():
            raise ConnectionRejected('fixture_probe_expired_or_busy')
        current.state = 'cleaning'
        current.cleanup_generation += 1
        current.save(update_fields=['state','cleanup_generation'])
    client = None
    try:
        adapter = get_storage_adapter(connection=current.connection)
        stat = adapter.complete_multipart(_runtime_key(current,'browser'),current.checks['uploads']['browser']['id'],
            [MultipartPart(1,put_etag)],expected_size=64,expected_part_size=64,expected_part_count=1,
            expected_upload_session_id=str(current.pk))
        _runtime_receipt(current,'browser',stat.version_id or 'null')
        if not stat.version_id or stat.version_id == 'null':
            raise ConnectionRejected('fixture_version_unavailable')
        client = build_client(current.connection)
        _runtime_read(client,current,'browser',stat.version_id,put_digest)
        _save_runtime(current,multipart=True,presigned_put=True,presigned_get=True,browser_sha256=True,browser_put_sha256=True)
    except Exception as error:
        code = error.code if isinstance(error,ConnectionRejected) else error_code(error)
        StorageConnectionProbe.objects.filter(pk=current.pk,state='cleaning',cleanup_generation=current.cleanup_generation).update(error_code=code)
        try:
            finish_cleanup(current,actor,browser_verified=False)
        except ConnectionRejected:
            pass
        raise ConnectionRejected(code,503) from None
    finally:
        if client is not None:
            client.close()
    return finish_cleanup(current,actor,browser_verified=True)


def _cleanup_runtime_fixture(probe,client):
    if probe.bucket != probe.connection.bucket or probe.object_key != 'staging/'+probe.pk.hex or probe.bucket_created:
        raise ConnectionRejected('fixture_ownership_unconfirmed')
    for role,receipt in probe.checks.get('uploads',{}).items():
        if role not in {'browser','abort'} or (receipt.get('started') and not receipt.get('id')):
            raise ConnectionRejected('fixture_multipart_receipt_missing')
        if receipt.get('id'):
            _abort_runtime_upload(probe,client,role,receipt['id'])
    objects = dict(probe.checks.get('objects',{}))
    for role in ('server','browser'):
        key = _runtime_key(probe,role)
        receipt = objects.get(role)
        if receipt and (receipt.get('key') != key or not receipt.get('version')):
            raise ConnectionRejected('fixture_ownership_unconfirmed')
        try:
            params = {'Bucket':probe.bucket,'Key':key,**({'VersionId':receipt['version']} if receipt else {})}
            stat = client.head_object(**params)
        except ClientError as error:
            if _object_missing(error):
                continue
            raise
        version = stat.get('VersionId') or 'null'
        if stat.get('Metadata',{}).get('bluedrive-probe-id') != str(probe.pk) or (receipt and receipt['version'] != version):
            raise ConnectionRejected('fixture_ownership_unconfirmed')
        if not receipt:
            objects[role] = {'key':key,'version':version}
            _save_runtime(probe,objects=objects)
        client.delete_object(Bucket=probe.bucket,Key=key,VersionId=version)
        try:
            client.head_object(Bucket=probe.bucket,Key=key,VersionId=version)
        except ClientError as error:
            if _object_missing(error):
                continue
            raise
        raise ConnectionRejected('fixture_delete_unconfirmed')
    _save_runtime(probe,delete_verified=True)
    return True


def reconcile_missing_lab_probe(probe,actor,reason,operator_client):
    """Operator chứng minh bucket LAB chưa tạo đã vắng; đóng lịch sử, không cấp READY."""
    reason = reason_text(reason)
    with transaction.atomic():
        require_configure(actor,probe.connection.cluster.tenant_id,lock=True)
        current = StorageConnectionProbe.objects.select_for_update().select_related('connection__cluster').get(pk=probe.pk)
        if (current.mode != 'lab' or current.bucket_created or current.state != 'cleanup_pending'
                or current.bucket != 'bluedrive-scc-'+current.pk.hex or current.object_key != 'staging/'+current.pk.hex):
            raise ConnectionRejected('fixture_absence_reconciliation_not_allowed')
        try:
            operator_client.head_bucket(Bucket=current.bucket)
        except ClientError as error:
            if not _missing(error):
                raise ConnectionRejected('fixture_absence_unconfirmed',503) from None
        else:
            raise ConnectionRejected('fixture_absence_unconfirmed',503)
        current.state,current.completed_at,current.error_code = 'failed',timezone.now(),'fixture_bucket_absent_reconciled'
        current.checks = {**current.checks,'operator_absence_verified':True,'cleanup':True}
        current.save(update_fields=['state','completed_at','error_code','checks'])
        ClusterAuditEvent.objects.create(cluster=current.connection.cluster,actor=actor,action='storage.connection.fixture_absence_reconciled',
            resource_ref=str(current.pk),before={'state':'cleanup_pending'},after={'state':'failed','mode':'lab'},reason=reason)
        return current
