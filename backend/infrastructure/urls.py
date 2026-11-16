from django.urls import path

from . import api
from . import connection_api
from . import telemetry_api


urlpatterns = [
    path('platform/live/', api.platform_live, name='platform-live'),
    path('clusters/<uuid:cluster_id>/telemetry/', telemetry_api.snapshot, name='telemetry'),
    path('clusters/<uuid:cluster_id>/telemetry/stream/', telemetry_api.stream, name='telemetry-stream'),
    path('clusters/<uuid:cluster_id>/alerts/', telemetry_api.alerts, name='storage-alerts'),
    path('clusters/<uuid:cluster_id>/alerts/<uuid:alert_id>/acknowledge/', telemetry_api.acknowledge, name='acknowledge-alert'),
    path('profiles/', connection_api.profiles, name='connection-profiles'),
    path('binding/', connection_api.binding, name='storage-binding'),
    path('clusters/connect/', connection_api.connect, name='connect-existing'),
    path('clusters/<uuid:cluster_id>/connections/', connection_api.cluster_connections, name='connections'),
    path('clusters/<uuid:cluster_id>/connections/<uuid:connection_id>/', connection_api.detail, name='connection-detail'),
    path('clusters/<uuid:cluster_id>/connections/<uuid:connection_id>/verify/', connection_api.verify, name='connection-verify'),
    path('clusters/<uuid:cluster_id>/connections/<uuid:connection_id>/probe/', connection_api.start_probe, name='connection-probe'),
    path('clusters/<uuid:cluster_id>/connections/<uuid:connection_id>/probes/<uuid:probe_id>/', connection_api.probe_status, name='probe-status'),
    path('clusters/<uuid:cluster_id>/connections/<uuid:connection_id>/probes/<uuid:probe_id>/complete/', connection_api.probe_complete, name='probe-complete'),
    path('clusters/<uuid:cluster_id>/connections/<uuid:connection_id>/probes/<uuid:probe_id>/cleanup/', connection_api.probe_cleanup, name='probe-cleanup'),
    path('access/events/', api.access_events, name='access-events'),
    path('access/<uuid:membership_id>/', api.storage_access, name='storage-access'),
    path('capabilities/', api.capabilities, name='capabilities'),
    path('clusters/', api.clusters, name='clusters'),
    path('clusters/<uuid:cluster_id>/', api.cluster_detail, name='cluster-detail'),
    path('clusters/<uuid:cluster_id>/topology/', api.topology, name='topology'),
    path('clusters/<uuid:cluster_id>/layout/', api.save_layout, name='save-layout'),
    path('clusters/<uuid:cluster_id>/nodes/', api.nodes, name='nodes'),
    path('clusters/<uuid:cluster_id>/nodes/<uuid:node_id>/', api.node_detail, name='node-detail'),
    path('clusters/<uuid:cluster_id>/disks/', api.disks, name='disks'),
    path('clusters/<uuid:cluster_id>/events/', api.events, name='events'),
    path('clusters/<uuid:cluster_id>/operations/', api.operations, name='operations'),
    path('clusters/<uuid:cluster_id>/operations/<uuid:job_id>/', api.operation_detail, name='operation-detail'),
]
