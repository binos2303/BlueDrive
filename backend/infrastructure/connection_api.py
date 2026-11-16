"""API kết nối hiện hữu: không nhận raw credential và không điều khiển node."""
from functools import wraps
import uuid

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.api_views import require_csrf
from files.storage_adapters.base import StorageError
from infrastructure import api as inventory
from infrastructure.connection_profiles import ProfileUnavailable, profiles_for, public_profile
from infrastructure.connections import (ConnectionRejected, activate_binding, binding_data, connection_data,
    register_connection, require_configure, scoped_connections, verify_read_only)
from infrastructure.connection_probes import begin_probe, cleanup_probe, complete_probe, runtime_authorizations, RUNTIME_REQUIRED
from infrastructure.models import PlatformStorageBinding, StorageBinding, StorageConnectionProbe


def endpoint(methods):
    def decorate(view):
        @wraps(view)
        def checked(*args,**kwargs):
            try:
                response = view(*args,**kwargs)
            except ConnectionRejected as error:
                response = Response({'detail':'Storage connection action could not be completed.','code':error.code},status=error.status)
            except ProfileUnavailable:
                response = Response({'detail':'The approved storage connection profile is unavailable.','code':'profile_unavailable'},status=503)
            except StorageError:
                response = Response({'detail':'Storage is temporarily unavailable.','code':'storage_unavailable'},status=503)
            response['Referrer-Policy'] = 'no-referrer'
            return response
        authenticated = authentication_classes([SessionAuthentication])(permission_classes([IsAuthenticated])(checked))
        return never_cache(require_csrf(api_view(methods)(authenticated)))
    return decorate


def _configure(request,tenant_id):
    inventory._access(request,tenant_id)
    require_configure(request.user,tenant_id)


def _connection(request,tenant_id,cluster_id,connection_id,*,configure=False):
    if configure:
        _configure(request,tenant_id)
    else:
        inventory._access(request,tenant_id)
    return get_object_or_404(scoped_connections(tenant_id),pk=connection_id,cluster_id=cluster_id)


def _origin(request):
    origins = settings.CORS_ALLOWED_ORIGINS
    origin = request.headers.get('Origin') or (origins[0] if origins else None)
    if not origin or origin not in origins:
        raise ConnectionRejected('browser_origin_not_approved',400)
    return origin


@endpoint(['GET'])
def profiles(request,tenant_id=None):
    _configure(request,tenant_id)
    return Response({'profiles':[public_profile(key,tenant_id) for key in sorted(profiles_for(tenant_id))]})


@endpoint(['POST'])
def connect(request,tenant_id=None):
    _configure(request,tenant_id)
    connection,created = register_connection(request.user,tenant_id,request.data,request.headers.get('Idempotency-Key',''))
    return Response({'cluster':inventory._cluster_data(connection.cluster),'connection':connection_data(connection)},status=201 if created else 200)


@endpoint(['GET','POST'])
def cluster_connections(request,cluster_id,tenant_id=None):
    cluster = inventory._cluster(request,cluster_id,tenant_id)
    if request.method == 'GET':
        return inventory._page(request,cluster.connections.all(),connection_data)
    _configure(request,tenant_id)
    connection,created = register_connection(request.user,tenant_id,request.data,request.headers.get('Idempotency-Key',''),cluster_id)
    return Response({'connection':connection_data(connection)},status=201 if created else 200)


@endpoint(['GET'])
def detail(request,cluster_id,connection_id,tenant_id=None):
    return Response(connection_data(_connection(request,tenant_id,cluster_id,connection_id)))


@endpoint(['POST'])
def verify(request,cluster_id,connection_id,tenant_id=None):
    connection = _connection(request,tenant_id,cluster_id,connection_id,configure=True)
    if not isinstance(request.data,dict) or set(request.data) != {'reason'}:
        raise ConnectionRejected('reason_required',400)
    result,checks = verify_read_only(connection,request.user,request.data['reason'],_origin(request))
    return Response({'connection':connection_data(result),'checks':checks},status=200 if not result.last_error_code else 503)


def _probe_data(probe):
    keys = {'head_bucket','versioning','cors','tls','sse_configured','server_sha256','version_pinned','sse_response','browser_sha256','cleanup',*RUNTIME_REQUIRED}
    return {'id':str(probe.pk),'mode':probe.mode,'state':probe.state,'expires_at':probe.expires_at,
            'expired':probe.expires_at <= timezone.now(), 'error_code':probe.error_code or None,
            'cleanup_bucket':probe.bucket if probe.state == 'cleanup_pending' and probe.mode == 'lab' else None,
            'checks':{key:value for key,value in probe.checks.items() if key in keys and type(value) is bool}}


@endpoint(['GET','POST'])
def start_probe(request,cluster_id,connection_id,tenant_id=None):
    connection = _connection(request,tenant_id,cluster_id,connection_id,configure=True)
    if request.method == 'GET':
        return Response({'probes':[_probe_data(probe) for probe in connection.probes.order_by('-created_at')[:20]]})
    if not isinstance(request.data,dict):
        raise ConnectionRejected('explicit_fixture_confirmation_required',400)
    mode = request.data.get('mode','lab')
    if mode == 'runtime':
        if set(request.data) != {'mode','reason','confirm_runtime_fixture'} or request.data['confirm_runtime_fixture'] is not True:
            raise ConnectionRejected('explicit_runtime_fixture_confirmation_required',400)
    elif mode != 'lab' or set(request.data) != {'reason','confirm_lab_fixture'} or request.data['confirm_lab_fixture'] is not True:
        raise ConnectionRejected('explicit_lab_fixture_confirmation_required',400)
    probe,url = begin_probe(connection,request.user,request.data['reason'],_origin(request),mode=mode)
    authorizations = runtime_authorizations(probe) if mode == 'runtime' else {'authorization':{'url':url,'expires_in':180}}
    return Response({'probe':_probe_data(probe),**authorizations},status=201)


def _probe(request,tenant_id,cluster_id,connection_id,probe_id):
    connection = _connection(request,tenant_id,cluster_id,connection_id,configure=True)
    return get_object_or_404(StorageConnectionProbe.objects.select_related('connection__cluster'),pk=probe_id,connection=connection)


@endpoint(['GET'])
def probe_status(request,cluster_id,connection_id,probe_id,tenant_id=None):
    probe = _probe(request,tenant_id,cluster_id,connection_id,probe_id)
    result = {'probe':_probe_data(probe)}
    if request.query_params.get('authorization') == '1' and probe.state == 'awaiting_browser' and probe.expires_at > timezone.now():
        from files.storage_adapters import get_storage_adapter
        ttl = min(180,int((probe.expires_at-timezone.now()).total_seconds()))
        if ttl > 0:
            if probe.mode == 'runtime':
                result.update(runtime_authorizations(probe,expires_in=ttl))
            else:
                signed = get_storage_adapter(connection=probe.connection,bucket=probe.bucket).create_download_url(probe.object_key,
                    version_id=probe.object_version_id,download_name='storage-verification.bin',expires_in=ttl)
                result['authorization'] = {'url':signed.url,'expires_in':ttl}
    return Response(result)


@endpoint(['POST'])
def probe_complete(request,cluster_id,connection_id,probe_id,tenant_id=None):
    probe = _probe(request,tenant_id,cluster_id,connection_id,probe_id)
    fields = {'sha256','put_sha256','put_etag'} if probe.mode == 'runtime' else {'sha256'}
    if not isinstance(request.data,dict) or set(request.data) != fields:
        raise ConnectionRejected('browser_fixture_digest_required',400)
    result = complete_probe(probe,request.user,request.data['sha256'],
        put_digest=request.data.get('put_sha256'),put_etag=request.data.get('put_etag'))
    result.connection.refresh_from_db()
    return Response({'probe':_probe_data(result),'connection':connection_data(result.connection)})


@endpoint(['POST'])
def probe_cleanup(request,cluster_id,connection_id,probe_id,tenant_id=None):
    probe = _probe(request,tenant_id,cluster_id,connection_id,probe_id)
    if request.data:
        raise ConnectionRejected('unexpected_cleanup_fields',400)
    return Response({'probe':_probe_data(cleanup_probe(probe,request.user))})


@endpoint(['GET','PATCH'])
def binding(request,tenant_id=None):
    _configure(request,tenant_id)
    if request.method == 'GET':
        workspace_id = request.query_params.get('workspace_id')
        if workspace_id:
            try:
                workspace_id = uuid.UUID(workspace_id)
            except ValueError:
                raise ConnectionRejected('binding_workspace_unavailable',400) from None
        if tenant_id is None:
            if workspace_id:
                raise ConnectionRejected('binding_workspace_unavailable',400)
            current = PlatformStorageBinding.objects.select_related('connection').filter(pk='primary').first()
        else:
            current = StorageBinding.objects.select_related('connection').filter(tenant_id=tenant_id,scope='workspace' if workspace_id else 'tenant',workspace_id=workspace_id,state='active').first()
        return Response({'binding':binding_data(current),'routing_enabled':settings.SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED})
    data = request.data
    if not isinstance(data,dict) or not {'connection_id','expected_generation','reason'} <= set(data) or set(data) - {'connection_id','expected_generation','reason','workspace_id'}:
        raise ConnectionRejected('binding_fields_required',400)
    try:
        identity = uuid.UUID(data['connection_id'])
        workspace_id = uuid.UUID(data['workspace_id']) if data.get('workspace_id') else None
    except (ValueError,TypeError,AttributeError):
        raise ConnectionRejected('binding_fields_required',400) from None
    if tenant_id is None and workspace_id is not None:
        raise ConnectionRejected('binding_workspace_unavailable',400)
    connection = get_object_or_404(scoped_connections(tenant_id),pk=identity)
    result,unchanged = activate_binding(connection,request.user,tenant_id,data['expected_generation'],data['reason'],workspace_id)
    return Response({'binding':binding_data(result),'unchanged':unchanged,'routing_enabled':settings.SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED})
