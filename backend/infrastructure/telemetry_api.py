"""Snapshot không gọi collector; stream chỉ báo client tải lại snapshot đúng scope."""
import asyncio
import re
from types import SimpleNamespace

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.handlers.asgi import ASGIRequest
from django.db import close_old_connections, transaction
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.models import Membership, Tenant
from infrastructure import api as inventory
from infrastructure.connection_api import endpoint
from infrastructure.models import ClusterAuditEvent, StorageAlert, StorageTelemetrySnapshot
from infrastructure.telemetry import alert_data, snapshot_data


def monitor(request,cluster_id,tenant_id):
    if not settings.SECUREDRIVE_STORAGE_MONITORING_ENABLED:
        raise Http404
    cluster = inventory._cluster(request,cluster_id,tenant_id)
    if not inventory._access(request,tenant_id).get('storage.monitor'):
        raise PermissionDenied('Storage monitoring permission is required.')
    return cluster


def supports_stream(request):
    return isinstance(request._request,ASGIRequest) and settings.SESSION_ENGINE in {'django.contrib.sessions.backends.db','django.contrib.sessions.backends.cached_db'}


@endpoint(['GET'])
def snapshot(request,cluster_id,tenant_id=None):
    return Response(snapshot_data(monitor(request,cluster_id,tenant_id),sse_available=supports_stream(request)))


@endpoint(['GET'])
def alerts(request,cluster_id,tenant_id=None):
    cluster = monitor(request,cluster_id,tenant_id)
    return inventory._page(request,StorageAlert.objects.filter(cluster=cluster),alert_data)


@endpoint(['POST'])
def acknowledge(request,cluster_id,alert_id,tenant_id=None):
    monitor(request,cluster_id,tenant_id)
    data = request.data
    if not isinstance(data,dict) or set(data) != {'expected_revision','reason'} or type(data['expected_revision']) is not int or not isinstance(data['reason'],str) or not 8 <= len(data['reason'].strip()) <= 500:
        raise ValidationError({'detail':'Provide expected_revision and an 8–500 character reason.'})
    with transaction.atomic():
        # Cùng thứ tự khóa với thay quyền; thu hồi quyền trước ACK phải có hiệu lực.
        if tenant_id:
            get_object_or_404(Tenant.objects.select_for_update(),pk=tenant_id,status='active')
            get_object_or_404(Membership.objects.select_for_update(),tenant_id=tenant_id,user=request.user,status='active')
        request.user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        cluster = monitor(request,cluster_id,tenant_id)
        row = get_object_or_404(StorageTelemetrySnapshot.objects.select_for_update(),cluster=cluster)
        alert = get_object_or_404(StorageAlert.objects.select_for_update(),pk=alert_id,cluster=cluster)
        if alert.acknowledged_at:
            return Response({'alert':alert_data(alert),'unchanged':True})
        if alert.revision != data['expected_revision'] or alert.resolved_at:
            return Response({'detail':'Alert changed. Refresh before acknowledging.','code':'alert_revision_conflict'},status=409)
        alert.acknowledged_at,alert.acknowledged_by = timezone.now(),request.user
        alert.revision += 1
        alert.save(update_fields=['acknowledged_at','acknowledged_by','revision'])
        row.revision += 1
        row.save(update_fields=['revision','updated_at'])
        ClusterAuditEvent.objects.create(cluster=cluster,actor=request.user,action='storage.alert.acknowledged',resource_ref=str(alert.pk),before={'revision':data['expected_revision']},after={'revision':alert.revision},reason=data['reason'].strip())
    return Response({'alert':alert_data(alert),'unchanged':False})


def authorized_event(session_key,user_id,cluster_id,tenant_id):
    close_old_connections()
    try:
        session = Session.objects.filter(session_key=session_key,expire_date__gt=timezone.now()).first()
        user = get_user_model().objects.filter(pk=user_id,is_active=True).first()
        if session is None or user is None:
            return None
        auth = session.get_decoded()
        hashes = [user.get_session_auth_hash(),*user.get_session_auth_fallback_hash()]
        if str(auth.get('_auth_user_id')) != str(user.pk) or not any(constant_time_compare(auth.get('_auth_user_hash',''),value) for value in hashes):
            return None
        cluster = monitor(SimpleNamespace(user=user),cluster_id,tenant_id)
        return snapshot_data(cluster)['event_id']
    except (Http404,PermissionDenied):
        return None
    finally:
        close_old_connections()


async def event_stream(session_key,user_id,cluster_id,tenant_id,cursor):
    # Stream có hạn; mỗi nhịp kiểm tra lại session và quyền thay vì giữ quyền lúc mở.
    for _ in range(12):
        identity = await sync_to_async(authorized_event,thread_sensitive=True)(session_key,user_id,cluster_id,tenant_id)
        if identity is None:
            yield 'event: access_revoked\ndata: {}\n\n'
            return
        if identity != cursor:
            yield f'id: {identity}\nevent: resync\ndata: {{}}\n\n'
            cursor = identity
        else:
            yield ': heartbeat\n\n'
        await asyncio.sleep(5)


@endpoint(['GET'])
def stream(request,cluster_id,tenant_id=None):
    monitor(request,cluster_id,tenant_id)
    if not supports_stream(request):
        return Response({'code':'stream_requires_asgi','detail':'Use snapshot polling on this deployment.'},status=503)
    cursor = request.headers.get('Last-Event-ID','')
    if cursor and (len(cursor) > 90 or not re.fullmatch(re.escape(str(cluster_id))+r':\d{1,20}:[01]',cursor)):
        raise ValidationError({'detail':'Invalid event cursor.'})
    response = StreamingHttpResponse(event_stream(request.session.session_key,request.user.pk,cluster_id,tenant_id,cursor),content_type='text/event-stream')
    response['Cache-Control'] = 'no-store, no-transform'
    response['X-Accel-Buffering'] = 'no'
    return response
