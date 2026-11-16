"""Connect-existing và binding metadata; mọi I/O đều dùng profile đã duyệt."""
import hashlib
import json
import re
import uuid
from datetime import timedelta

from botocore.exceptions import ClientError, SSLError, ConnectTimeoutError, ReadTimeoutError, EndpointConnectionError, BotoCoreError
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError
from django.utils import timezone

from accounts.models import Tenant, Workspace
from accounts.platform_admin import is_platform_super_admin, is_platform_admin
from files.models import StorageConfig
from files.storage_adapters.base import StorageError
from infrastructure.connection_profiles import profile_spec, profiles_for, public_profile, build_client, ProfileUnavailable
from infrastructure.models import (
    ClusterAuditEvent, PlatformStorageBinding, StorageBinding, StorageAccessGrant,
    StorageCluster, StorageConnectionRevision, StorageConnectionProbe,
)


class ConnectionRejected(Exception):
    def __init__(self,code,status=409):
        self.code, self.status = code, status
        super().__init__(code)


def require_configure(actor,tenant_id,*,lock=False):
    users = get_user_model().objects.all()
    if lock:
        if tenant_id is not None:
            if not Tenant.objects.select_for_update().filter(pk=tenant_id,kind='business',status='active').exists():
                raise ConnectionRejected('storage_context_unavailable',404)
        users = users.select_for_update(no_key=True)
    current = users.filter(pk=actor.pk,is_active=True).first()
    if current is None:
        raise ConnectionRejected('storage_configure_required',403)
    if tenant_id is None:
        if not is_platform_super_admin(current):
            raise ConnectionRejected('storage_configure_required',403)
    else:
        granted = set(StorageAccessGrant.objects.filter(membership__tenant_id=tenant_id,membership__tenant__status='active',
            membership__tenant__kind='business',membership__user_id=current.pk,membership__status='active').values_list('permission',flat=True))
        if is_platform_admin(current) or not {'storage.view','storage.configure'} <= granted:
            raise ConnectionRejected('storage_configure_required',403)


def reason_text(value):
    if not isinstance(value,str) or not 8 <= len(value.strip()) <= 500:
        raise ConnectionRejected('reason_required',400)
    return value.strip()


def request_key(key,tenant_id,cluster_id=None):
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{8,128}',key):
        raise ConnectionRejected('idempotency_key_required',400)
    return uuid.uuid5(uuid.NAMESPACE_URL,f'bluedrive:storage:{tenant_id or "platform"}:{cluster_id or "connect"}:{key}')


def connection_data(connection):
    latest = connection.probes.order_by('-generation','-created_at').first()
    return {'id':str(connection.pk),'cluster_id':str(connection.cluster_id),'revision':connection.revision,
            'profile_id':connection.profile_id,'endpoint_url':connection.endpoint_url,
            'public_endpoint_url':connection.public_endpoint_url,'bucket':connection.bucket,
            'state':connection.state,'read_verified_at':connection.read_verified_at,
            'verified_at':connection.verified_at,'last_error_code':connection.last_error_code or None,
            'verification_scope':latest.mode if latest else 'lab' if connection.lab else 'read_only',
            'verification_generation':connection.verification_generation}


def scoped_connections(tenant_id):
    query = StorageConnectionRevision.objects.select_related('cluster')
    return query.filter(cluster__kind='platform',cluster__tenant__isnull=True) if tenant_id is None else query.filter(cluster__kind='enterprise',cluster__tenant_id=tenant_id,cluster__tenant__status='active')


def register_connection(actor,tenant_id,data,key,cluster_id=None):
    expected = {'profile_id','reason'} if cluster_id else {'profile_id','reason','display_name','slug'}
    if not isinstance(data,dict) or set(data) != expected:
        raise ConnectionRejected('approved_profile_required',400)
    reason = reason_text(data['reason'])
    if not isinstance(data['profile_id'],str) or len(data['profile_id']) > 100:
        raise ConnectionRejected('approved_profile_required',400)
    if not cluster_id and (not isinstance(data['display_name'],str) or not 1 <= len(data['display_name'].strip()) <= 200 or not isinstance(data['slug'],str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}',data['slug'])):
        raise ConnectionRejected('invalid_cluster_name',400)
    identity = request_key(key,tenant_id,cluster_id)
    digest = hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    existing = scoped_connections(tenant_id).filter(request_key=identity).first()
    if existing:
        if existing.request_digest != digest:
            raise ConnectionRejected('idempotency_conflict')
        return existing,False
    spec = profile_spec(data['profile_id'],tenant_id,resolve=True)
    profile = profiles_for(tenant_id)[data['profile_id']]
    try:
        with transaction.atomic():
            require_configure(actor,tenant_id,lock=True)
            if tenant_id:
                tenant = Tenant.objects.select_for_update().get(pk=tenant_id,kind='business',status='active')
            else:
                tenant = None
            if cluster_id:
                cluster = StorageCluster.objects.select_for_update().get(pk=cluster_id,kind='platform' if tenant is None else 'enterprise',tenant=tenant)
                if cluster.provider != profile['provider'] or cluster.state == 'retired':
                    raise ConnectionRejected('cluster_profile_conflict')
                latest = cluster.connections.order_by('-revision').first()
                revision = latest.revision + 1 if latest else 1
            else:
                cluster = StorageCluster.objects.create(kind='platform' if tenant is None else 'enterprise',tenant=tenant,
                    display_name=data['display_name'].strip(),slug=data['slug'],provider=profile['provider'],
                    edition=profile.get('edition',''),provider_version=profile.get('provider_version',''),created_by=actor)
                revision = 1
            connection = StorageConnectionRevision.objects.create(cluster=cluster,revision=revision,
                profile_id=data['profile_id'],request_key=identity,request_digest=digest,created_by=actor,**spec)
            ClusterAuditEvent.objects.create(cluster=cluster,actor=actor,action='storage.connection.registered',
                resource_ref=str(connection.pk),after={'revision':revision,'state':'draft'},reason=reason)
            return connection,True
    except (Tenant.DoesNotExist,StorageCluster.DoesNotExist):
        raise ConnectionRejected('storage_context_unavailable',404) from None
    except IntegrityError:
        existing = scoped_connections(tenant_id).filter(request_key=identity,request_digest=digest).first()
        if existing:
            return existing,False
        raise ConnectionRejected('cluster_conflict') from None


def error_code(error):
    if isinstance(error,ProfileUnavailable):
        return 'profile_unavailable'
    if isinstance(error,SSLError):
        return 'tls_validation_failed'
    if isinstance(error,(ConnectTimeoutError,ReadTimeoutError,EndpointConnectionError)):
        return 'storage_unreachable'
    if isinstance(error,ClientError):
        code = error.response.get('Error',{}).get('Code','')
        if code in {'AccessDenied','InvalidAccessKeyId','SignatureDoesNotMatch','403','InvalidToken'}:
            return 'storage_identity_rejected'
        if code in {'NoSuchBucket','NoSuchKey','404','NotFound'}:
            return 'storage_not_found'
    return 'storage_check_failed'


def _cors_ready(rules,origin):
    methods = set()
    upload_receipt = False
    for rule in rules:
        if origin in rule.get('AllowedOrigins',[]) or '*' in rule.get('AllowedOrigins',[]):
            methods.update(rule.get('AllowedMethods',[]))
            exposed = {value.lower() for value in rule.get('ExposeHeaders',[])}
            headers = {value.lower() for value in rule.get('AllowedHeaders',[])}
            if 'PUT' in rule.get('AllowedMethods',[]) and 'etag' in exposed and ('*' in headers or 'content-type' in headers):
                upload_receipt = True
    return {'GET','PUT','HEAD'} <= methods and upload_receipt


def inspect_read_only(client,connection,browser_origin):
    client.head_bucket(Bucket=connection.bucket)
    checks = {'head_bucket':True,'versioning':False,'cors':False,
              'tls':connection.endpoint_url.startswith('https://'),'sse_configured':bool(connection.server_side_encryption)}
    try:
        checks['versioning'] = client.get_bucket_versioning(Bucket=connection.bucket).get('Status') == 'Enabled'
        checks['cors'] = _cors_ready(client.get_bucket_cors(Bucket=connection.bucket).get('CORSRules',[]),browser_origin)
    except ClientError:
        # HEAD thành công chưa đủ để chứng nhận policy upload/browser.
        checks['policy_read_available'] = False
    return checks


def verify_read_only(connection,actor,reason,browser_origin):
    reason = reason_text(reason)
    with transaction.atomic():
        require_configure(actor,connection.cluster.tenant_id,lock=True)
        current = StorageConnectionRevision.objects.select_for_update().get(pk=connection.pk)
        lease_active = current.verification_started_at and current.verification_started_at > timezone.now()-timedelta(minutes=2)
        if (current.state == 'verifying' and lease_active) or current.probes.filter(state__in=['creating','awaiting_browser','cleaning','cleanup_pending']).exists():
            raise ConnectionRejected('connection_check_in_progress')
        was_ready = current.state == 'ready'
        current.verification_generation += 1
        current.verification_started_at = timezone.now()
        generation = current.verification_generation
        if not was_ready:
            current.state = 'verifying'
        current.save(update_fields=['verification_generation','verification_started_at','state'])
    client = None
    try:
        client = build_client(current)
        checks = inspect_read_only(client,current,browser_origin)
        code = ''
    except (BotoCoreError,ClientError,StorageError,OSError) as error:
        checks,code = {},error_code(error)
    finally:
        if client is not None:
            client.close()
    with transaction.atomic():
        current = StorageConnectionRevision.objects.select_for_update().get(pk=connection.pk)
        if current.verification_generation != generation:
            raise ConnectionRejected('connection_check_superseded')
        current.last_error_code = code
        if not code:
            current.read_verified_at = timezone.now()
        current.state = 'ready' if was_ready else 'failed' if code else 'read_verified'
        current.save(update_fields=['last_error_code','read_verified_at','state'])
        ClusterAuditEvent.objects.create(cluster=current.cluster,actor=actor,action='storage.connection.read_checked',
            resource_ref=str(current.pk),after={'state':current.state,'revision':current.revision},reason=reason)
    return current,checks


def binding_data(binding):
    if binding is None:
        return {'connection_id':None,'generation':0}
    return {'connection_id':str(binding.connection_id) if binding.connection_id else None,
            'generation':binding.generation,'cluster_id':str(binding.connection.cluster_id) if binding.connection_id else str(binding.cluster_id)}


def activate_binding(connection,actor,tenant_id,expected_generation,reason,workspace_id=None):
    reason = reason_text(reason)
    if type(expected_generation) is not int or expected_generation < 0:
        raise ConnectionRejected('binding_generation_required',400)
    try:
        with transaction.atomic():
            require_configure(actor,tenant_id,lock=True)
            if tenant_id is not None:
                tenant = Tenant.objects.select_for_update().get(pk=tenant_id,kind='business',status='active')
            else:
                tenant = None
            current = scoped_connections(tenant_id).select_for_update(of=('self',)).get(pk=connection.pk)
            if current.state != 'ready' or current.last_error_code or current.cluster.state != 'ready' or not current.probes.filter(state='succeeded').exists():
                raise ConnectionRejected('full_transfer_verification_required')
            if tenant is None:
                binding = PlatformStorageBinding.objects.select_for_update().filter(pk='primary').first()
            else:
                workspace = None
                if workspace_id is not None:
                    workspace = Workspace.objects.filter(pk=workspace_id,tenant=tenant,status='active').first()
                    if workspace is None:
                        raise ConnectionRejected('binding_workspace_unavailable',404)
                binding = StorageBinding.objects.select_for_update().filter(tenant=tenant,scope='workspace' if workspace else 'tenant',workspace=workspace,state='active').first()
            if binding and binding.connection_id == current.pk:
                return binding,True
            generation = binding.generation if binding else 0
            if generation != expected_generation:
                raise ConnectionRejected('binding_generation_conflict')
            if tenant is None:
                binding, _ = PlatformStorageBinding.objects.update_or_create(pk='primary',defaults={'connection':current,'generation':generation+1,'updated_by':actor})
            else:
                if StorageBinding.objects.filter(tenant=tenant,state='active').exclude(cluster=current.cluster).exclude(pk=binding.pk if binding else None).exists():
                    raise ConnectionRejected('organization_has_another_active_cluster')
                config, _ = StorageConfig.objects.get_or_create(tenant=tenant,provider=current.cluster.provider,
                    defaults={'endpoint':current.endpoint_url,'status':'active'})
                if binding:
                    binding.state = 'retired'
                    binding.save(update_fields=['state'])
                binding = StorageBinding.objects.create(tenant=tenant,scope='workspace' if workspace else 'tenant',workspace=workspace,
                    cluster=current.cluster,storage_config=config,connection=current,state='active',active_since=timezone.now(),generation=generation+1)
            ClusterAuditEvent.objects.create(cluster=current.cluster,actor=actor,action='storage.binding.prepared',
                resource_ref=str(current.pk),after={'revision':binding.generation},reason=reason)
            return binding,False
    except IntegrityError:
        raise ConnectionRejected('binding_conflict') from None
