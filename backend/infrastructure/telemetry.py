"""Current summary và incident lifecycle; không lưu chuỗi mẫu thô vào DB."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, F, Q
from django.utils import timezone

from infrastructure.models import StorageAlert, StorageCluster, StorageTelemetrySnapshot
from infrastructure.prometheus import CLUSTER_METRICS, NODE_METRICS, REQUIRED, MonitoringError, fetch_metrics, profile_for, valid_value


def claim_collection(cluster,plan):
    with transaction.atomic():
        StorageCluster.objects.select_for_update().get(pk=cluster.pk)
        row,_ = StorageTelemetrySnapshot.objects.select_for_update().get_or_create(cluster=cluster)
        if plan['revision'] < row.profile_revision or (plan['revision'] == row.profile_revision and row.profile_fingerprint and row.profile_fingerprint != plan['fingerprint']):
            raise MonitoringError('monitoring_profile_revision_conflict')
        if row.profile_fingerprint and row.profile_fingerprint != plan['fingerprint']:
            row.last_error_code = 'monitoring_profile_changed'
            row.revision += 1
        row.profile_id,row.profile_revision,row.profile_fingerprint = plan['id'],plan['revision'],plan['fingerprint']
        row.stale_after_seconds = plan['stale_after_seconds']
        row.generation += 1
        row.last_attempted_at = timezone.now()
        row.save()
        return row.generation


def clean_payload(payload,node_ids):
    if not isinstance(payload,dict):
        return {'cluster_metrics':{},'node_metrics':{}}
    cluster = payload.get('cluster_metrics',{})
    nodes = payload.get('node_metrics',{})
    result = {'cluster_metrics':{key:value for key,value in cluster.items() if key in CLUSTER_METRICS and valid_value(key,value)} if isinstance(cluster,dict) else {},'node_metrics':{}}
    if isinstance(nodes,dict):
        for identity,metrics in nodes.items():
            if identity in node_ids and isinstance(metrics,dict):
                result['node_metrics'][identity] = {key:value for key,value in metrics.items() if key in NODE_METRICS and valid_value(key,value)}
    return result


def conditions(metrics,plan=None):
    result = {}
    if metrics.get('cluster_read_ready') == 0: result['read_quorum_lost'] = 'critical'
    if metrics.get('cluster_write_ready') == 0: result['write_quorum_lost'] = 'critical'
    if metrics.get('cluster_failed_disks',0) > 0: result['disk_failures'] = 'warning'
    if metrics.get('cluster_offline_nodes',0) > 0: result['nodes_unavailable'] = 'warning'
    capacity,free = metrics.get('usable_capacity_bytes'),metrics.get('usable_free_bytes')
    if capacity and free is not None and free <= capacity:
        percent = 100 * (capacity-free)/capacity
        thresholds = (plan or {}).get('capacity_thresholds',{'warning':80,'critical':95})
        if percent >= thresholds['critical']: result['capacity_critical'] = 'critical'
        elif percent >= thresholds['warning']: result['capacity_warning'] = 'warning'
    return result


def update_alerts(cluster,active,observed_at,*,resolve=False):
    current = {row.code:row for row in StorageAlert.objects.filter(cluster=cluster,resolved_at__isnull=True)}
    for code,severity in active.items():
        row = current.get(code)
        if row is None:
            StorageAlert.objects.create(cluster=cluster,code=code,severity=severity,first_seen_at=observed_at,last_seen_at=observed_at)
        elif observed_at > row.last_seen_at:
            row.last_seen_at = observed_at
            row.save(update_fields=['last_seen_at'])
    if resolve:
        for code,row in current.items():
            if code not in active:
                row.resolved_at = timezone.now()
                row.revision += 1
                row.save(update_fields=['resolved_at','revision'])


def publish_collection(cluster,plan,generation,payload=None,observed_at=None,error_code=''):
    with transaction.atomic():
        row = StorageTelemetrySnapshot.objects.select_for_update().get(cluster=cluster)
        if row.generation != generation or row.profile_fingerprint != plan['fingerprint'] or row.profile_revision != plan['revision']:
            return False
        now = timezone.now()
        nodes = set(str(value) for value in cluster.nodes.values_list('pk',flat=True))
        sanitized = clean_payload(payload,nodes)
        if not error_code:
            if observed_at is None or timezone.is_naive(observed_at) or not now-timedelta(seconds=row.stale_after_seconds) <= observed_at <= now+timedelta(seconds=5) or not REQUIRED <= set(sanitized['cluster_metrics']):
                error_code = 'source_samples_stale_or_missing'
            elif row.observed_at and observed_at < row.observed_at:
                error_code = 'source_observation_regressed'
            elif sanitized['cluster_metrics'].get('usable_free_bytes',0) > sanitized['cluster_metrics'].get('usable_capacity_bytes',2**63-1):
                error_code = 'source_values_inconsistent'
        changed = row.last_error_code != error_code
        row.last_error_code = error_code
        if not error_code:
            changed |= row.payload != sanitized or row.observed_at != observed_at or row.source_profile_id != plan['id']
            row.payload,row.observed_at,row.last_success_at,row.source_profile_id = sanitized,observed_at,observed_at,plan['id']
            update_alerts(cluster,conditions(sanitized['cluster_metrics'],plan),observed_at,resolve=True)
        else:
            update_alerts(cluster,{'collector_unavailable':'warning'},now)
        if changed:
            row.revision += 1
        row.save()
        return True


def collect(cluster,plan):
    if not settings.SECUREDRIVE_STORAGE_MONITORING_ENABLED:
        raise MonitoringError('monitoring_not_enabled')
    if cluster.state == 'retired' or (cluster.tenant_id and cluster.tenant.status != 'active'):
        raise MonitoringError('monitoring_scope_unavailable')
    generation = claim_collection(cluster,plan)
    node_ids = set(str(value) for value in cluster.nodes.values_list('pk',flat=True))
    if len(node_ids) > 500:
        publish_collection(cluster,plan,generation,error_code='monitoring_inventory_too_large')
        return False
    try:
        payload,observed_at = fetch_metrics(plan,node_ids)
    except MonitoringError as error:
        publish_collection(cluster,plan,generation,error_code=error.code)
        return False
    applied = publish_collection(cluster,plan,generation,payload,observed_at)
    return applied and not StorageTelemetrySnapshot.objects.get(cluster=cluster).last_error_code


def freshness(row,plan,profile_error='',now=None):
    now = now or timezone.now()
    if plan is None: return True,profile_error or 'monitoring_not_configured'
    if row is None or row.observed_at is None: return True,'samples_not_collected'
    if row.profile_revision != plan['revision'] or row.profile_fingerprint != plan['fingerprint']: return True,'monitoring_profile_changed'
    if row.last_error_code: return True,'collector_unavailable'
    if row.observed_at > now+timedelta(seconds=5) or row.observed_at < now-timedelta(seconds=row.stale_after_seconds): return True,'samples_stale'
    return False,''


def alert_data(row,now=None):
    return {'id':str(row.pk),'cluster_id':str(row.cluster_id),'code':row.code,'severity':row.severity,'revision':row.revision,
            'first_seen_at':row.first_seen_at,'last_seen_at':row.last_seen_at,'resolved_at':row.resolved_at,
            'acknowledged_at':row.acknowledged_at,'acknowledged_by':row.acknowledged_by_id}


def snapshot_data(cluster,*,sse_available=False,now=None):
    now = now or timezone.now()
    profile_error = ''
    try:
        plan = profile_for(cluster)
    except MonitoringError as error:
        plan,profile_error = None,error.code
    row = StorageTelemetrySnapshot.objects.filter(cluster=cluster).first()
    stale,reason = freshness(row,plan,profile_error,now)
    ids = set(str(value) for value in cluster.nodes.values_list('pk',flat=True))
    payload = clean_payload(row.payload if row else {},ids)
    metrics = payload['cluster_metrics']
    if not REQUIRED <= set(metrics) and not stale:
        stale,reason = True,'source_samples_missing'
    source = 'prometheus:'+row.source_profile_id if row and row.source_profile_id else 'not_collected'
    base = {'observed_at':row.observed_at if row else None,'source':source,'last_success_at':row.last_success_at if row else None,'stale':stale}
    warnings = conditions(metrics,plan) if not stale else {}
    status = 'unknown' if stale else 'critical' if 'critical' in warnings.values() else 'degraded' if warnings else 'healthy'
    health = {**base,'status':status,'reason_code':reason or next(iter(warnings),'current_sources_ready')}
    nodes = {}
    for identity,values in payload['node_metrics'].items():
        confirmed = not stale and values.get('node_seaweedfs_up') == 1 and values.get('node_host_up') == 1 and metrics.get('cluster_failed_disks') == 0 and status == 'healthy'
        nodes[identity] = {'metrics':values,'health':{**base,'status':'healthy' if confirmed else 'unknown','reason_code':reason or ('current_sources_ready' if confirmed else 'node_health_not_confirmed')}}
    alerts = [alert_data(alert,now) for alert in StorageAlert.objects.filter(cluster=cluster,resolved_at__isnull=True)]
    revision = row.revision if row else 0
    return {'cluster_id':str(cluster.pk),'configured':plan is not None,'revision':revision,'event_id':f'{cluster.pk}:{revision}:{int(stale)}',
            'health':health,'expires_at':row.observed_at+timedelta(seconds=row.stale_after_seconds) if row and row.observed_at else None,
            'cluster_metrics':metrics,'nodes':nodes,'alerts':alerts,'sse_available':sse_available,'poll_seconds':30}


def sweep_stale(limit=100):
    count = 0
    active = StorageAlert.objects.filter(cluster_id=OuterRef('cluster_id'),code='telemetry_stale',resolved_at__isnull=True)
    # Bỏ incident đã mở để một nhóm cluster cũ không chặn các cluster phía sau.
    candidates = StorageTelemetrySnapshot.objects.annotate(already_stale=Exists(active)).filter(already_stale=False).filter(Q(observed_at__isnull=True) | Q(observed_at__lt=timezone.now()-F('stale_after_seconds')*timedelta(seconds=1))).order_by('observed_at','cluster_id')
    for identity in candidates.values_list('cluster_id',flat=True)[:limit]:
        with transaction.atomic():
            row = StorageTelemetrySnapshot.objects.select_for_update().select_related('cluster').get(cluster_id=identity)
            if row.observed_at is None or row.observed_at < timezone.now()-timedelta(seconds=row.stale_after_seconds):
                before = StorageAlert.objects.filter(cluster=row.cluster,code='telemetry_stale',resolved_at__isnull=True).exists()
                update_alerts(row.cluster,{'telemetry_stale':'warning'},timezone.now())
                if not before:
                    row.revision += 1; row.save(update_fields=['revision','updated_at'])
                count += 1
    return count
