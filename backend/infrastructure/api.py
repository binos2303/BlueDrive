"""Inventory và quyền storage; provider I/O nằm trong connection_api."""
import logging
import math
import ipaddress
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.api_views import require_csrf
from accounts.models import Membership, Tenant
from accounts.platform_admin import is_platform_admin, is_platform_super_admin
from infrastructure.platform_live import read_platform_status, build_platform_alerts
from infrastructure.models import (
    STORAGE_PERMISSIONS, ClusterAuditEvent, ClusterOperationJob, NodeDisk,
    StorageAccessGrant, StorageCluster, StorageNode, TopologyLayout,
)

logger = logging.getLogger(__name__)


def _deny(request, tenant_id, resource_id=None):
    logger.warning('Storage inventory access denied: actor_id=%s scope=%s requested_resource=%s', request.user.pk, 'platform' if tenant_id is None else 'organization', resource_id)
    raise Http404('Storage inventory is unavailable.')


def _access(request, tenant_id):
    if not settings.SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED:
        raise Http404('Storage inventory is unavailable.')
    if not request.user.is_active:
        _deny(request, tenant_id)
    if tenant_id is None:
        if not is_platform_admin(request.user):
            _deny(request, tenant_id)
        # Chỉ Super Admin cấu hình kho Platform; vận hành node thuộc gate sau.
        return {permission: permission in {'storage.view', 'storage.monitor'} or (permission == 'storage.configure' and is_platform_super_admin(request.user)) for permission in STORAGE_PERMISSIONS}
    if is_platform_admin(request.user):
        _deny(request, tenant_id)
    granted = set(StorageAccessGrant.objects.filter(
        membership__tenant_id=tenant_id, membership__tenant__kind='business',
        membership__tenant__status='active', membership__user_id=request.user.pk,
        membership__user__is_active=True, membership__status='active',
    ).values_list('permission', flat=True))
    if 'storage.view' not in granted:
        _deny(request, tenant_id)
    return {permission: permission in granted for permission in STORAGE_PERMISSIONS}


def _clusters(tenant_id):
    if tenant_id is None:
        return StorageCluster.objects.filter(kind='platform', tenant__isnull=True)
    return StorageCluster.objects.filter(kind='enterprise', tenant_id=tenant_id, tenant__kind='business', tenant__status='active')


def _cluster(request, cluster_id, tenant_id):
    _access(request, tenant_id)
    try:
        return get_object_or_404(_clusters(tenant_id), pk=cluster_id)
    except Http404:
        _deny(request, tenant_id, cluster_id)


def _page(request, queryset, serialize):
    try:
        page = int(request.query_params.get('page', '1'))
        size = int(request.query_params.get('page_size', '50'))
        if not 1 <= page <= 100000 or not 1 <= size <= 100:
            raise ValueError
    except (ValueError, TypeError):
        raise ValidationError({'detail': 'page must be 1–100000 and page_size must be 1–100.'}) from None
    count = queryset.count()
    records = queryset[(page - 1) * size:page * size]
    return Response({'count': count, 'page': page, 'page_size': size, 'has_more': page * size < count, 'results': [serialize(record) for record in records]})


def _health():
    # Inventory không phải nguồn telemetry; không suy Healthy từ record hoặc IP.
    return {'status': 'unknown', 'observed_at': None, 'source': 'not_collected', 'last_success_at': None, 'stale': True, 'reason_code': 'telemetry_not_configured'}


def _cluster_data(cluster):
    return {
        'id': str(cluster.pk), 'kind': cluster.kind,
        'tenant_id': str(cluster.tenant_id) if cluster.tenant_id else None,
        'display_name': cluster.display_name, 'slug': cluster.slug,
        'provider': cluster.provider, 'edition': cluster.edition,
        'provider_version': cluster.provider_version, 'state': cluster.state,
        'verified_at': cluster.verified_at, 'revision': cluster.revision,
        'health': _health(), 'created_at': cluster.created_at,
    }


def _node_data(node):
    labels = node.labels if isinstance(node.labels, dict) else {}
    addresses = []
    for value in node.private_ips[:16] if isinstance(node.private_ips, list) else []:
        try:
            if isinstance(value, str):
                addresses.append(str(ipaddress.ip_address(value)))
        except ValueError:
            continue
    return {
        'id': str(node.pk), 'cluster_id': str(node.cluster_id),
        'pool_id': str(node.pool_id) if node.pool_id else None,
        'agent_identity': str(node.agent_identity) if node.agent_identity else None,
        'hostname': node.hostname, 'private_ips': addresses,
        'labels': {key: value for key, value in labels.items() if key in {'zone', 'rack', 'role', 'environment'} and isinstance(value, str) and len(value) <= 200},
        'inventory_status': node.inventory_status, 'last_seen': node.last_seen,
        'health': _health(),
    }


def _disk_data(disk):
    return {'id': str(disk.pk), 'node_id': str(disk.node_id), 'stable_disk_id': disk.stable_disk_id,
            'mount_path': disk.mount_path, 'capacity_bytes': disk.capacity_bytes, 'capacity_source': 'inventory',
            'inventory_status': disk.state, 'last_seen': disk.last_seen, 'health': _health()}


def _operation_data(job):
    return {'id': str(job.pk), 'cluster_id': str(job.cluster_id), 'kind': job.kind,
            'state': job.state, 'dry_run': job.dry_run, 'plan_hash': job.plan_hash,
            'requested_by': job.requested_by_id, 'approved_by': job.approved_by_id,
            'expires_at': job.expires_at, 'lease_version': job.lease_version,
            'created_at': job.created_at, 'updated_at': job.updated_at}


def _audit_data(event):
    allowed = {'display_name', 'state', 'revision', 'inventory_status', 'hostname', 'desired_status', 'kind'}
    def projection(value):
        if not isinstance(value, dict):
            return {}
        result = {key: item for key, item in value.items() if key in allowed and (item is None or type(item) in {str, int, bool}) and (not isinstance(item, str) or len(item) <= 200)}
        if isinstance(value.get('permissions'), list):
            result['permissions'] = sorted({item for item in value['permissions'] if isinstance(item, str) and item in STORAGE_PERMISSIONS})
        return result
    return {'id': str(event.pk), 'actor_id': event.actor_id, 'action': event.action,
            'resource_ref': event.resource_ref, 'before': projection(event.before),
            'after': projection(event.after), 'reason': event.reason, 'created_at': event.created_at}


def _finite(value, lower, upper):
    return type(value) in {int, float} and lower <= value <= upper and math.isfinite(value)


def _layout_data(layout, node_ids):
    data = {'revision': 0, 'scope': 'personal', 'positions': {}, 'viewport': {'x': 0, 'y': 0, 'zoom': 1}}
    if layout is None:
        return data
    data.update(revision=layout.revision, scope='personal' if layout.owner_user_id else 'shared')
    positions = layout.positions if isinstance(layout.positions, dict) else {}
    data['positions'] = {key: {'x': value['x'], 'y': value['y']} for key, value in positions.items()
                         if key in node_ids and isinstance(value, dict) and _finite(value.get('x'), -1000000, 1000000) and _finite(value.get('y'), -1000000, 1000000)}
    viewport = layout.viewport if isinstance(layout.viewport, dict) else {}
    if _finite(viewport.get('x'), -1000000, 1000000) and _finite(viewport.get('y'), -1000000, 1000000) and _finite(viewport.get('zoom'), .1, 4):
        data['viewport'] = {key: viewport[key] for key in ('x', 'y', 'zoom')}
    return data


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def capabilities(request, tenant_id=None):
    permissions = _access(request, tenant_id)
    return Response({'scope': 'platform' if tenant_id is None else 'organization',
                     'tenant_id': str(tenant_id) if tenant_id else None, 'permissions': permissions,
                     'operations_enabled': False, 'routing_enabled': settings.SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED,
                     'lab_probes_enabled':settings.SECUREDRIVE_STORAGE_LAB_PROBES_ENABLED,
                     'runtime_probes_enabled':settings.SECUREDRIVE_STORAGE_RUNTIME_PROBES_ENABLED,
                     'topology_enabled':settings.SECUREDRIVE_STORAGE_TOPOLOGY_ENABLED,
                     'monitoring_enabled':settings.SECUREDRIVE_STORAGE_MONITORING_ENABLED,
                     'stage': 'topology' if settings.SECUREDRIVE_STORAGE_TOPOLOGY_ENABLED else 'connect_existing'})


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def clusters(request, tenant_id=None):
    _access(request, tenant_id)
    queryset = _clusters(tenant_id)
    query = request.query_params.get('q', '').strip()[:100]
    if query:
        queryset = queryset.filter(display_name__icontains=query)
    return _page(request, queryset, _cluster_data)


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def cluster_detail(request, cluster_id, tenant_id=None):
    return Response(_cluster_data(_cluster(request, cluster_id, tenant_id)))


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def topology(request, cluster_id, tenant_id=None):
    cluster = _cluster(request, cluster_id, tenant_id)
    nodes = list(cluster.nodes.all()[:501])
    pools = list(cluster.pools.all()[:501])
    disks = list(NodeDisk.objects.filter(node__cluster=cluster)[:2001])
    if len(nodes) > 500 or len(pools) > 500 or len(disks) > 2000:
        return Response({'detail': 'Use the paginated node and disk lists for this cluster.', 'code': 'topology_snapshot_too_large'}, status=422)
    node_ids = {str(node.pk) for node in nodes}
    personal = TopologyLayout.objects.filter(cluster=cluster, owner_user=request.user).first()
    shared = TopologyLayout.objects.filter(cluster=cluster, owner_user__isnull=True).first()
    layout = personal or shared
    grouped = {}
    for node in nodes:
        grouped.setdefault(node.pool_id, []).append(str(node.pk))
    return Response({'cluster': _cluster_data(cluster), 'cluster_id': str(cluster.pk),
                     'revision': cluster.revision, 'observed_at': None, 'health': _health(),
                     'pools': [{'id': str(pool.pk), 'name': pool.name, 'generation': pool.generation, 'desired_status': pool.desired_status, 'node_ids': grouped.get(pool.pk, [])} for pool in pools],
                     'nodes': [_node_data(node) for node in nodes], 'disks': [_disk_data(disk) for disk in disks],
                     'layout': _layout_data(layout, node_ids),
                     'layout_revisions':{'personal':personal.revision if personal else 0,'shared':shared.revision if shared else 0}})


@require_csrf
@api_view(['PATCH'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def save_layout(request,cluster_id,tenant_id=None):
    if not settings.SECUREDRIVE_STORAGE_TOPOLOGY_ENABLED:
        raise Http404('Storage topology is unavailable.')
    cluster = _cluster(request,cluster_id,tenant_id)
    data = request.data
    if not isinstance(data,dict) or set(data) != {'scope','expected_revision','positions','viewport'}:
        raise ValidationError({'detail':'Only layout scope, expected revision, positions and viewport are accepted.'})
    scope,expected,positions,viewport = (data[key] for key in ('scope','expected_revision','positions','viewport'))
    if scope not in ('personal','shared') or type(expected) is not int or not 0 <= expected < 2**63-1:
        raise ValidationError({'detail':'Invalid layout scope or expected revision.'})
    if not isinstance(positions,dict) or len(positions) > 500 or any(not isinstance(value,dict) or set(value) != {'x','y'} or not all(_finite(value.get(axis),-1000000,1000000) for axis in ('x','y')) for value in positions.values()):
        raise ValidationError({'detail':'Layout positions must contain at most 500 finite x/y coordinates.'})
    if not isinstance(viewport,dict) or set(viewport) != {'x','y','zoom'} or not _finite(viewport.get('x'),-1000000,1000000) or not _finite(viewport.get('y'),-1000000,1000000) or not _finite(viewport.get('zoom'),.1,4):
        raise ValidationError({'detail':'Invalid layout viewport.'})
    with transaction.atomic():
        # Cùng thứ tự khóa với cấp/thu hồi quyền; không lưu sau khi grant đã bị thu hồi.
        if tenant_id is not None:
            Tenant.objects.select_for_update().get(pk=tenant_id)
        actor = get_user_model().objects.select_for_update(no_key=True).filter(pk=request.user.pk,is_active=True).first()
        if actor is None:
            raise Http404('Storage topology is unavailable.')
        request.user = actor
        permissions = _access(request,tenant_id)
        if scope == 'shared' and not permissions.get('storage.configure'):
            return Response({'detail':'Shared layout changes require storage.configure.'},status=403)
        cluster = StorageCluster.objects.select_for_update().get(pk=cluster.pk)
        node_ids = {str(value) for value in cluster.nodes.values_list('pk',flat=True)}
        if set(positions) - node_ids:
            raise ValidationError({'detail':'Layout contains a node outside the selected cluster. Reload topology and retry.'})
        layout = TopologyLayout.objects.filter(cluster=cluster,owner_user=actor if scope == 'personal' else None).first()
        revision = layout.revision if layout else 0
        if layout and layout.positions == positions and layout.viewport == viewport:
            return Response({'layout':_layout_data(layout,node_ids),'unchanged':True})
        if revision != expected:
            return Response({'detail':'Layout changed in another window. Reload the saved layout before retrying.','code':'layout_revision_conflict','current_revision':revision},status=409)
        if layout is None:
            layout = TopologyLayout(cluster=cluster,owner_user=actor if scope == 'personal' else None)
        layout.positions,layout.viewport,layout.revision = positions,viewport,revision+1
        layout.save()
        if scope == 'shared':
            ClusterAuditEvent.objects.create(cluster=cluster,actor=actor,action='storage.layout.shared_updated',resource_ref=str(layout.pk),before={'revision':revision},after={'revision':layout.revision},reason='Shared display layout updated; inventory unchanged.')
        return Response({'layout':_layout_data(layout,node_ids),'unchanged':False})


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def nodes(request, cluster_id, tenant_id=None):
    cluster = _cluster(request, cluster_id, tenant_id)
    queryset = cluster.nodes.all()
    query = request.query_params.get('q', '').strip()[:100]
    if query:
        queryset = queryset.filter(hostname__icontains=query)
    return _page(request, queryset, _node_data)


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def node_detail(request, cluster_id, node_id, tenant_id=None):
    cluster = _cluster(request, cluster_id, tenant_id)
    try:
        node = get_object_or_404(StorageNode, pk=node_id, cluster=cluster)
    except Http404:
        _deny(request, tenant_id, node_id)
    return Response({**_node_data(node), 'disk_count': node.disks.count()})


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def disks(request, cluster_id, tenant_id=None):
    cluster = _cluster(request, cluster_id, tenant_id)
    query = NodeDisk.objects.filter(node__cluster=cluster)
    node = _node_filter(request,cluster)
    if node:
        query = query.filter(node=node)
    return _page(request, query, _disk_data)


def _node_filter(request,cluster):
    identity = request.query_params.get('node_id')
    if identity is None:
        return None
    try:
        identity = uuid.UUID(identity)
    except (ValueError,TypeError,AttributeError):
        raise ValidationError({'detail':'Invalid node selector.'}) from None
    return get_object_or_404(StorageNode,pk=identity,cluster=cluster)


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def events(request, cluster_id, tenant_id=None):
    cluster = _cluster(request, cluster_id, tenant_id)
    query = ClusterAuditEvent.objects.filter(cluster=cluster)
    node = _node_filter(request,cluster)
    if node:
        query = query.filter(resource_ref=str(node.pk))
    return _page(request, query, _audit_data)


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def operations(request, cluster_id, tenant_id=None):
    cluster = _cluster(request, cluster_id, tenant_id)
    return _page(request, ClusterOperationJob.objects.filter(cluster=cluster), _operation_data)


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def operation_detail(request, cluster_id, job_id, tenant_id=None):
    cluster = _cluster(request, cluster_id, tenant_id)
    try:
        job = get_object_or_404(ClusterOperationJob, cluster=cluster, pk=job_id)
    except Http404:
        _deny(request, tenant_id, job_id)
    return Response(_operation_data(job))


def _owner(request, tenant_id, *, lock=False):
    if not settings.SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED or tenant_id is None:
        raise Http404('Storage access management is unavailable.')
    if not request.user.is_active or is_platform_admin(request.user):
        _deny(request, tenant_id)
    tenants = Tenant.objects.all()
    members = Membership.objects.all()
    if lock:
        tenants = tenants.select_for_update()
        members = members.select_for_update()
    tenant = get_object_or_404(tenants, pk=tenant_id, kind='business', status='active')
    get_object_or_404(members, tenant=tenant, user=request.user, role='owner', status='active')
    return tenant


def _permissions_list(value):
    if not isinstance(value, list) or len(value) > len(STORAGE_PERMISSIONS) or any(not isinstance(item, str) or item not in STORAGE_PERMISSIONS for item in value) or len(set(value)) != len(value):
        raise ValidationError({'detail': 'Provide a unique list of supported storage permissions.'})
    return sorted(value)


@require_csrf
@api_view(['GET', 'PATCH'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def storage_access(request, membership_id, tenant_id=None):
    tenant = _owner(request, tenant_id)
    target = get_object_or_404(Membership, pk=membership_id, tenant=tenant)
    if request.method == 'GET':
        return Response({'membership_id': str(target.pk), 'permissions':sorted(target.storage_grants.values_list('permission', flat=True))})
    data = request.data
    if not isinstance(data, dict) or set(data) != {'permissions', 'expected_permissions', 'reason'}:
        raise ValidationError({'detail': 'Provide permissions, expected_permissions and reason.'})
    desired = _permissions_list(data['permissions'])
    expected = _permissions_list(data['expected_permissions'])
    reason = data['reason']
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 500:
        raise ValidationError({'detail': 'Reason must contain 8–500 characters.'})
    with transaction.atomic():
        tenant = _owner(request, tenant_id, lock=True)
        target = get_object_or_404(Membership.objects.select_for_update(), pk=membership_id, tenant=tenant)
        users = {user.pk:user for user in get_user_model().objects.select_for_update().filter(pk__in=[request.user.pk, target.user_id]).order_by('pk')}
        actor = users[request.user.pk]
        receiver = users[target.user_id]
        if not actor.is_active or is_platform_admin(actor):
            _deny(request, tenant_id)
        if desired and (target.status != 'active' or not receiver.is_active or is_platform_admin(receiver)):
            _deny(request, tenant_id)
        current = sorted(target.storage_grants.values_list('permission', flat=True))
        if current == desired:
            return Response({'membership_id':str(target.pk), 'permissions':current, 'unchanged':True})
        if current != expected:
            return Response({'detail':'Storage access changed. Refresh before saving.', 'code':'storage_access_conflict'}, status=409)
        target.storage_grants.exclude(permission__in=desired).delete()
        StorageAccessGrant.objects.bulk_create([
            StorageAccessGrant(membership=target, permission=permission, granted_by=request.user, reason=reason.strip())
            for permission in desired if permission not in current
        ])
        ClusterAuditEvent.objects.create(tenant=tenant, actor=request.user, action='storage.access.changed',
                                        resource_ref=str(target.pk), before={'permissions':current}, after={'permissions':desired}, reason=reason.strip())
    return Response({'membership_id':str(target.pk), 'permissions':desired, 'unchanged':False})


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def access_events(request, tenant_id=None):
    tenant = _owner(request, tenant_id)
    return _page(request, ClusterAuditEvent.objects.filter(tenant=tenant, cluster__isnull=True), _audit_data)


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def platform_live(request):
    """Dashboard trực tiếp cho Platform, không tạo node hay điều khiển Docker."""
    _access(request, None)
    from infrastructure.models import PlatformStorageBinding
    binding = PlatformStorageBinding.objects.select_related('connection__cluster').filter(pk='primary').first()
    result = read_platform_status()
    result['routing_enabled'] = settings.SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED
    result['binding_ready'] = bool(binding and binding.connection.state == 'ready' and
                                   binding.connection.cluster.state == 'ready')
    result['binding_revision'] = binding.connection.revision if binding else None
    result['alerts'] = build_platform_alerts(result)
    return Response(result)
