"""Thu thập tài nguyên Docker lab an toàn; backend chỉ đọc snapshot đã kiểm tra.

Chạy trên Windows host, không cho Django hoặc browser quyền gọi Docker Engine.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / '.local'
DEST = LOCAL / 'platform-metrics.json'
NODE_NAME = re.compile(r'volume(?:[2-9]|1[0-2])?\Z')
APPROVED = {'master', 'filer', 's3', 'postgres', 'volume', 'volume2', 'volume3'}
CONTAINER = re.compile(r'bluedrive-seaweedfs-(master|filer|s3|postgres|volume(?:[2-9]|1[0-2])?)-1\Z')
UNITS = {'B': 1, 'kB': 1000, 'MB': 1000**2, 'GB': 1000**3, 'TB': 1000**4,
         'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3, 'TiB': 1024**4}
SIZE = re.compile(r'^([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)$')


def extra_names():
    path = LOCAL / 'platform-nodes.json'
    if not path.is_file() or path.stat().st_size > 4096:
        return set()
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return set()
    extras = data.get('extra_nodes') if isinstance(data, dict) else None
    if not isinstance(extras, list) or len(extras) > 9:
        return set()
    return {name for name in extras if isinstance(name, str) and NODE_NAME.fullmatch(name) and name not in APPROVED}


def parse_bytes(raw):
    match = SIZE.fullmatch(raw.strip()) if isinstance(raw, str) else None
    if not match or match.group(2) not in UNITS:
        return None
    value = int(float(match.group(1)) * UNITS[match.group(2)])
    return value if 0 <= value < 10**18 else None


def parse_pair(raw):
    if not isinstance(raw, str) or raw.count('/') != 1:
        return (None, None)
    first, second = raw.split('/')
    return parse_bytes(first), parse_bytes(second)


def parse_cpu(raw):
    if not isinstance(raw, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?%', raw):
        return None
    value = float(raw[:-1])
    return value if 0 <= value <= 100000 else None


def parse_df(output):
    """df -Pk trả về KiB của filesystem gắn /data, không phải ổ vật lý riêng."""
    for line in reversed(output.splitlines()):
        fields = line.split()
        if len(fields) >= 6 and fields[-1] == '/data' and all(field.isdecimal() for field in fields[-5:-2]):
            capacity = int(fields[-5]) * 1024
            available = int(fields[-3]) * 1024
            if 0 < capacity < 10**18 and 0 <= available <= capacity:
                return capacity, available
    return (None, None)


def docker(*args, required=True):
    try:
        process = subprocess.run(['docker', *args], capture_output=True, text=True, encoding='utf-8',
                                 timeout=18, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if required:
            raise RuntimeError('Docker CLI unavailable or timed out') from exc
        return None
    if process.returncode != 0:
        if required:
            raise RuntimeError('Docker command failed (details omitted; may contain private paths)')
        return None
    return process.stdout


def collect():
    approved = APPROVED | extra_names()
    listed = docker('ps', '--filter', 'label=com.docker.compose.project=bluedrive-seaweedfs',
                    '--format', '{{.Names}}')
    running = {}
    for line in listed.splitlines():
        match = CONTAINER.fullmatch(line.strip())
        if match and match.group(1) in approved:
            running[line.strip()] = match.group(1)
    if not running:
        raise RuntimeError('No approved running Platform containers')
    stats_raw = docker('stats', '--no-stream', '--format', '{{json .}}', *sorted(running))
    stats = {}
    for line in stats_raw.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = record.get('Name')
        if name in running:
            stats[running[name]] = record
    if not stats:
        raise RuntimeError('Docker stats returned no approved records')
    containers = {}
    for docker_name, service in running.items():
        row = stats.get(service, {})
        mem_used, mem_limit = parse_pair(row.get('MemUsage'))
        net_rx, net_tx = parse_pair(row.get('NetIO'))
        status_raw = docker('inspect', '--format', '{{json .State.Health.Status}}', docker_name,
                            required=False)
        health = 'unknown'
        if status_raw:
            try:
                health = json.loads(status_raw.strip())
            except (ValueError, TypeError):
                pass
        if health not in ('healthy', 'unhealthy', 'starting'):
            health = 'unknown'
        disk_total = disk_available = None
        if NODE_NAME.fullmatch(service):
            disk_raw = docker('exec', docker_name, 'df', '-Pk', '/data', required=False)
            if disk_raw:
                disk_total, disk_available = parse_df(disk_raw)
        containers[service] = {
            'running': True,
            'docker_health': health,
            'cpu_percent': parse_cpu(row.get('CPUPerc')),
            'memory_used_bytes': mem_used,
            'memory_limit_bytes': mem_limit,
            'network_rx_bytes': net_rx,
            'network_tx_bytes': net_tx,
            'disk_total_bytes': disk_total,
            'disk_available_bytes': disk_available,
        }
    return {'schema': 1, 'sampled_at': datetime.now(timezone.utc).isoformat(),
            'source': 'docker_cli', 'containers': containers}


def write_sample(sample):
    LOCAL.mkdir(parents=True, exist_ok=True)
    tmp = LOCAL / ('platform-metrics.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(sample, separators=(',', ':')), encoding='utf-8')
        os.replace(tmp, DEST)
    finally:
        if tmp.exists():
            tmp.unlink()


def main():
    parser = argparse.ArgumentParser(description='Read-only Docker resource sampling for Platform Storage Dashboard')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--once', action='store_true', help='Sample once and exit')
    mode.add_argument('--watch', action='store_true', help='Sample repeatedly until Ctrl+C')
    parser.add_argument('--interval', type=int, default=15, help='Sampling interval in seconds (10..300)')
    args = parser.parse_args()
    if not 10 <= args.interval <= 300:
        parser.error('--interval must be between 10 and 300 seconds')
    while True:
        try:
            sample = collect()
            write_sample(sample)
            print(f"{sample['sampled_at']} Docker metrics: {len(sample['containers'])} services", flush=True)
        except RuntimeError as error:
            print(f'Monitoring collection failed: {error}', file=sys.stderr, flush=True)
            # Không ghi snapshot giả để che khuất dữ liệu stale.
            if not args.watch:
                return 1
        if not args.watch:
            return 0
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0


if __name__ == '__main__':
    sys.exit(main())
