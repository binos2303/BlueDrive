"""Trạng thái SeaweedFS Platform từ Master API thật, chỉ đọc.

Không biến thông tin topology thành cảnh báo phần cứng: /dir/status chỉ cung cấp
Volume Server đã đăng ký và volume slots, KHÔNG cung cấp dung lượng ổ đĩa vật lý.
"""
import http.client
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

MAX_BODY = 512 * 1024
METRICS_MAX_BODY = 64 * 1024
METRICS_MAX_AGE_SECONDS = 60
BASE_NODES = ('volume', 'volume2', 'volume3')
EXTRA_PATTERN = re.compile(r'volume(?:[4-9]|1[0-2])\Z')


def expected_nodes():
    """Node bổ sung trong lab được ghi sau khi thực sự đăng ký với Master.

    Registry chỉ lưu tên node, không chứa secrets hay địa chỉ tùy ý.
    """
    path = Path(settings.BASE_DIR).parent / 'infra' / 'seaweedfs' / '.local' / 'platform-nodes.json'
    try:
        if path.stat().st_size > 4096:
            return BASE_NODES
        registry = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return BASE_NODES
    extras = registry.get('extra_nodes', []) if isinstance(registry, dict) else []
    if not isinstance(extras, list) or len(extras) > 9:
        return BASE_NODES
    trusted = sorted({node for node in extras if isinstance(node, str) and EXTRA_PATTERN.fullmatch(node)}, key=lambda node: int(node[6:]))
    return BASE_NODES + tuple(trusted)


def parse_topology(payload):
    # Node không đăng ký vẫn xuất hiện Offline theo registry được duyệt.
    expected = expected_nodes()
    topology = payload.get('Topology') if isinstance(payload, dict) else None
    if not isinstance(topology, dict):
        raise ValueError('invalid_master_topology')
    registered = {}
    for dc in topology.get('DataCenters', []):
        if not isinstance(dc, dict):
            continue
        for rack in dc.get('Racks', []):
            if not isinstance(rack, dict):
                continue
            for entry in rack.get('DataNodes', []):
                if not isinstance(entry, dict):
                    continue
                address = entry.get('Url', '')
                if not isinstance(address, str):
                    continue
                host = address.split(':')[0]
                if host not in expected or host in registered:
                    continue
                def number(key):
                    value = entry.get(key, 0)
                    return value if type(value) is int and 0 <= value <= 100000 else 0
                registered[host] = {
                    'id': host, 'address': address[:100], 'online': True,
                    'datacenter': str(dc.get('Id', ''))[:80],
                    'rack': str(rack.get('Id', ''))[:80],
                    'max_slots': number('Max'),
                    # /dir/status v4.53 có thể thiếu Free. Tính từ Max - Volumes;
                    # không được hiểu missing Free là hết slot.
                    'free_slots': min(number('Free'), number('Max')) if type(entry.get('Free')) is int
                    else max(0, number('Max') - number('Volumes')),
                    'volumes': number('Volumes'),
                }
    return [registered.get(host, {
        'id': host, 'address': '', 'online': False,
        'datacenter': '', 'rack': '', 'max_slots': 0,
        'free_slots': 0, 'volumes': 0,
    }) for host in expected]


def _local_master_url():
    value = settings.SECUREDRIVE_PLATFORM_SEAWEEDFS_MASTER_URL.rstrip('/')
    parsed = urlsplit(value)
    # Chặn SSRF, redirect hoặc endpoint public. Production cần collector nội bộ riêng.
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.port != 9333 or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('master_endpoint_not_approved')
    return value


def _read_master_json(path):
    parsed = urlsplit(_local_master_url())
    # HTTPConnection không tự theo redirect; Master API chỉ được gọi qua loopback.
    client = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
    try:
        client.request('GET', path, headers={'Accept': 'application/json'})
        response = client.getresponse()
        if response.status != 200:
            raise ValueError('master_unavailable')
        raw = response.read(MAX_BODY + 1)
    finally:
        client.close()
    if len(raw) > MAX_BODY:
        raise ValueError('topology_too_large')
    return json.loads(raw)


def _stored_volume_bytes(payload):
    """Dữ liệu volume.Size từ /vol/status, KHÔNG phải dung lượng ổ vật lý."""
    expected = expected_nodes()
    result = {host: 0 for host in expected}
    tree = payload.get('Volumes', {}).get('DataCenters', {}) if isinstance(payload, dict) else {}
    if not isinstance(tree, dict):
        raise ValueError('invalid_volume_status')
    for racks in tree.values():
        if not isinstance(racks, dict):
            continue
        for servers in racks.values():
            if not isinstance(servers, dict):
                continue
            for endpoint, volumes in servers.items():
                if not isinstance(endpoint, str) or endpoint.split(':')[0] not in expected or not isinstance(volumes, list):
                    continue
                hostname = endpoint.split(':')[0]
                for volume in volumes[:1000]:
                    if isinstance(volume, dict) and type(volume.get('Size')) is int and 0 <= volume['Size'] <= 10**15:
                        result[hostname] += volume['Size']
    return result


def _s3_gateway_responding():
    # S3 root yêu cầu IAM và thường trả HTTP 403: đó là dấu hiệu gateway trả lời,
    # KHÔNG đồng nghĩa đã xác minh credential hoặc tình trạng dữ liệu.
    client = http.client.HTTPConnection('127.0.0.1', 8333, timeout=2)
    try:
        client.request('GET', '/')
        return client.getresponse().status == 403
    except (OSError, http.client.HTTPException):
        return False
    finally:
        client.close()


def _read_docker_metrics():
    """Chỉ nhận snapshot Docker đã chuẩn hóa; không cho HTTP request gọi Docker CLI.

    Khi quá hạn, giữ thời điểm đo nhưng không trả lại chỉ số cũ như số liệu trực tiếp.
    """
    empty = {'state': 'not_collected', 'sampled_at': None, 'containers': {}}
    path = Path(settings.BASE_DIR).parent / 'infra' / 'seaweedfs' / '.local' / 'platform-metrics.json'
    try:
        if path.stat().st_size > METRICS_MAX_BODY:
            return {**empty, 'state': 'invalid'}
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return empty
    except (OSError, ValueError, UnicodeError):
        return {**empty, 'state': 'invalid'}
    if not isinstance(raw, dict) or raw.get('schema') != 1 or raw.get('source') != 'docker_cli':
        return {**empty, 'state': 'invalid'}
    timestamp = raw.get('sampled_at')
    try:
        date = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else None
    except ValueError:
        date = None
    if not date or not date.tzinfo:
        return {**empty, 'state': 'invalid'}
    delta = (timezone.now() - date).total_seconds()
    if not -30 <= delta <= METRICS_MAX_AGE_SECONDS:
        return {**empty, 'state': 'stale', 'sampled_at': date.isoformat()}
    rows = raw.get('containers')
    if not isinstance(rows, dict) or len(rows) > 24:
        return {**empty, 'state': 'invalid'}
    accepted = set(expected_nodes()) | {'master', 'filer', 'postgres', 's3'}
    numbers = ('cpu_percent', 'memory_used_bytes', 'memory_limit_bytes',
               'network_rx_bytes', 'network_tx_bytes', 'disk_total_bytes', 'disk_available_bytes')
    containers = {}
    for name, item in rows.items():
        if name not in accepted or not isinstance(item, dict):
            continue
        if item.get('running') is not True:
            continue
        result = {'docker_health': item.get('docker_health') if item.get('docker_health') in
                  ('healthy', 'unhealthy', 'starting') else 'unknown'}
        for key in numbers:
            value = item.get(key)
            if type(value) in (int, float) and 0 <= value <= 10**18 and (key != 'cpu_percent' or value <= 100000):
                result[key] = value
            else:
                result[key] = None
        containers[name] = result
    return {'state': 'fresh', 'sampled_at': date.isoformat(), 'containers': containers}


def _collection_inventory(payload):
    """Đếm bản ghi volume/collection của node đã duyệt; không suy ra replication health."""
    tree = payload.get('Volumes', {}).get('DataCenters', {}) if isinstance(payload, dict) else {}
    if not isinstance(tree, dict):
        return []
    allowed = set(expected_nodes())
    found = {}
    for racks in tree.values():
        if not isinstance(racks, dict):
            continue
        for servers in racks.values():
            if not isinstance(servers, dict):
                continue
            for endpoint, rows in servers.items():
                if not isinstance(endpoint, str) or endpoint.split(':')[0] not in allowed or not isinstance(rows, list):
                    continue
                for row in rows[:500]:
                    if not isinstance(row, dict):
                        continue
                    name, volume_id, size = row.get('Collection'), row.get('Id'), row.get('Size')
                    if not isinstance(name, str) or len(name) > 80 or type(volume_id) is not int or not 0 <= volume_id < 10**10:
                        continue
                    entry = found.setdefault(name, {'name': name, 'volume_copies': 0, 'volume_ids': set(), 'stored_bytes': 0})
                    entry['volume_copies'] += 1
                    entry['volume_ids'].add(volume_id)
                    if type(size) is int and 0 <= size <= 10**15:
                        entry['stored_bytes'] += size
    return [dict(name=item['name'], unique_volumes=len(item['volume_ids']),
                 volume_copies=item['volume_copies'], stored_bytes=item['stored_bytes'])
            for item in sorted(found.values(), key=lambda entry: entry['name'])[:40]]


def build_platform_alerts(status):
    """Cảnh báo tức thời, không phải log sự cố hoặc bằng chứng SLA."""
    alerts = []
    def add(severity, code, title, detail):
        alerts.append({'severity': severity, 'code': code, 'title': title, 'detail': detail})
    if not status.get('master_online'):
        add('critical', 'master_unavailable', 'Master unavailable', 'Topology cannot be verified.')
    else:
        for node in status.get('nodes', []):
            if not node['online']:
                add('warning', 'node_unregistered', node['id'] + ' not registered', 'The expected Volume Server is absent from Master topology.')
    if not status.get('s3_gateway_responding'):
        add('warning', 's3_probe_failed', 'S3 Gateway probe failed', 'The local gateway did not return the expected HTTP response.')
    metrics = status.get('docker_metrics', {})
    if metrics.get('state') == 'fresh':
        containers = metrics.get('containers', {})
        for name, item in containers.items():
            if item.get('docker_health') == 'unhealthy':
                add('warning', 'docker_unhealthy', name + ' Docker health failed', 'Docker reports this service as unhealthy.')
        # Named Docker volumes on one host can share the same filesystem; do not sum capacity.
        checked = []
        for name in expected_nodes():
            item = containers.get(name, {})
            total, available = item.get('disk_total_bytes'), item.get('disk_available_bytes')
            if type(total) is int and total > 0 and type(available) is int:
                checked.append((name, available / total))
        if checked and min(percent for _, percent in checked) < 0.10:
            add('critical', 'filesystem_pressure', 'Storage filesystem has less than 10% free',
                'Docker /data mount filesystem; multiple nodes may share this disk.')
    if status.get('routing_enabled') and not status.get('binding_ready'):
        add('critical', 'routing_without_binding', 'Routing has no ready Platform binding',
            'New uploads cannot safely choose the Platform connection.')
    return alerts


def read_platform_status():
    observed = timezone.now().isoformat()
    data = {
        'source': 'seaweedfs_master', 'observed_at': observed,
        'master_online': False, 'nodes': parse_topology({'Topology': {'DataCenters': []}}),
        'error_code': None,
    }
    try:
        data['nodes'] = parse_topology(_read_master_json('/dir/status'))
        data['master_online'] = True
    except (OSError, ValueError, http.client.HTTPException):
        data['error_code'] = 'platform_master_unavailable'
    try:
        volume_status = _read_master_json('/vol/status') if data['master_online'] else None
        stored = _stored_volume_bytes(volume_status) if volume_status is not None else None
        data['collections'] = _collection_inventory(volume_status) if volume_status is not None else []
    except (OSError, ValueError, http.client.HTTPException):
        stored = None
        data['collections'] = []
    for node in data['nodes']:
        node['stored_bytes'] = stored[node['id']] if stored is not None and node['online'] else None
    data['stored_volume_bytes'] = sum(stored[node['id']] for node in data['nodes'] if node['online']) if stored is not None else None
    data['s3_gateway_responding'] = _s3_gateway_responding()
    data['online_nodes'] = sum(1 for node in data['nodes'] if node['online'])
    data['volume_slots'] = sum(node['max_slots'] for node in data['nodes'] if node['online'])
    data['free_slots'] = sum(node['free_slots'] for node in data['nodes'] if node['online'])
    data['used_volume_slots'] = data['volume_slots'] - data['free_slots']
    # Không khẳng định disk bytes/CPU/RAM: Master API không báo các số đó.
    data['physical_disk_bytes_available'] = None
    data['docker_metrics'] = _read_docker_metrics()
    return data
