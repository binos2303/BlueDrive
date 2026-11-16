"""Prometheus chỉ đọc qua profile operator; không nhận PromQL/URL từ browser."""
import hashlib
import ipaddress
import json
import math
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout
from datetime import datetime, timezone as datetime_timezone
from urllib.parse import urlencode

from django.conf import settings
from django.utils import timezone
from urllib3.util import Timeout

from infrastructure.connection_profiles import origin, resolve_addresses, pinned_pool_classes, ProfileUnavailable

CLUSTER_METRICS = {'cluster_read_ready','cluster_write_ready','cluster_failed_disks','cluster_offline_nodes','raw_capacity_bytes','usable_capacity_bytes','usable_free_bytes','logical_used_bytes'}
NODE_METRICS = {'node_cpu_percent','node_ram_percent','node_uptime_seconds','node_filesystem_free_bytes','node_network_rx_bytes_per_second','node_network_tx_bytes_per_second','node_seaweedfs_up','node_host_up'}
REQUIRED = {'cluster_read_ready','cluster_write_ready','cluster_failed_disks','cluster_offline_nodes'}
BOOLEAN_METRICS = {'cluster_read_ready','cluster_write_ready','node_seaweedfs_up','node_host_up'}


class MonitoringError(Exception):
    def __init__(self,code):
        self.code = code
        super().__init__(code)


def profile_for(cluster,profile_id=None):
    registry = settings.SECUREDRIVE_STORAGE_MONITORING_PROFILES
    if not isinstance(registry,dict) or len(registry) > 100:
        raise MonitoringError('monitoring_profile_unavailable')
    candidates = [(key,value) for key,value in registry.items() if isinstance(value,dict) and value.get('cluster_id') == str(cluster.pk) and (profile_id is None or key == profile_id)]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise MonitoringError('monitoring_profile_ambiguous')
    identity,data = candidates[0]
    allowed = {'scope','tenant_id','cluster_id','revision','approved','review_ref','edition','provider_version','metrics_schema','endpoint_url','allowed_networks','token_env','ca_bundle','lab','stale_after_seconds','expected_labels','queries','capacity_thresholds'}
    try:
        if not isinstance(identity,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}',identity) or set(data)-allowed or data.get('approved') is not True:
            raise ValueError
        if type(data.get('revision')) is not int or not 1 <= data['revision'] <= 1000000000:
            raise ValueError
        if not isinstance(data.get('review_ref'),str) or not 8 <= len(data['review_ref']) <= 200:
            raise ValueError
        scope = 'platform' if cluster.kind == 'platform' else 'organization'
        if data.get('scope') != scope or data.get('tenant_id') != (None if cluster.tenant_id is None else str(cluster.tenant_id)):
            raise ValueError
        if cluster.provider != 's3' or not cluster.provider_version or data.get('edition') != cluster.edition or data.get('provider_version') != cluster.provider_version:
            raise ValueError
        schema = data.get('metrics_schema')
        if schema != 'seaweedfs_v1':
            raise ValueError
        lab = data.get('lab',False)
        if type(lab) is not bool:
            raise ValueError
        endpoint = data['endpoint_url'].rstrip('/')
        origin(endpoint,lab=lab)
        networks = data['allowed_networks']
        if not isinstance(networks,list) or not 1 <= len(networks) <= 16:
            raise ValueError
        for network in networks:
            ipaddress.ip_network(network,strict=True)
        if not isinstance(data.get('token_env'),str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{1,127}',data['token_env']):
            raise ValueError
        if not isinstance(data.get('ca_bundle',''),str) or len(data.get('ca_bundle','')) > 1024:
            raise ValueError
        ttl = data.get('stale_after_seconds',90)
        if type(ttl) is not int or not 45 <= ttl <= 900:
            raise ValueError
        labels = data['expected_labels']
        if not isinstance(labels,dict) or not 1 <= len(labels) <= 10 or labels.get('bluedrive_cluster_id') != str(cluster.pk):
            raise ValueError
        if any(not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,63}',key) or not isinstance(value,str) or not 1 <= len(value) <= 256 for key,value in labels.items()):
            raise ValueError
        queries = data['queries']
        if not isinstance(queries,dict) or not REQUIRED <= set(queries) or set(queries)-(CLUSTER_METRICS|NODE_METRICS):
            raise ValueError
        if any(not isinstance(query,dict) or set(query) != {'expr','timestamp_expr'} or any(not isinstance(value,str) or not 1 <= len(value) <= 2048 for value in query.values()) for query in queries.values()):
            raise ValueError
        thresholds = data.get('capacity_thresholds',{'warning':80,'critical':95})
        if not isinstance(thresholds,dict) or set(thresholds) != {'warning','critical'} or any(type(value) not in {int,float} or not 1 <= value <= 100 or not math.isfinite(value) for value in thresholds.values()) or not thresholds['warning'] < thresholds['critical']:
            raise ValueError
        plan = {**data,'endpoint_url':endpoint,'lab':lab,'ca_bundle':data.get('ca_bundle',''),'stale_after_seconds':ttl,'capacity_thresholds':thresholds,'id':identity}
        plan['fingerprint'] = hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
        return plan
    except (ValueError,TypeError,KeyError,AttributeError,ProfileUnavailable):
        raise MonitoringError('monitoring_profile_unavailable') from None


def valid_value(name,value):
    if type(value) not in {int,float} or not 0 <= value <= 2**63-1 or not math.isfinite(value):
        return False
    if name in BOOLEAN_METRICS:
        return value in (0,1)
    if name in {'node_cpu_percent','node_ram_percent'}:
        return value <= 100
    if name in {'cluster_failed_disks','cluster_offline_nodes'}:
        return value == int(value) and value <= 1000000
    return value <= 2**63-1


def make_pool(plan):
    try:
        scheme,host,port = origin(plan['endpoint_url'],lab=plan['lab'])
        addresses = resolve_addresses(plan['endpoint_url'],plan['allowed_networks'],plan['lab'])
        pools = pinned_pool_classes(plan['endpoint_url'],addresses,lab=plan['lab'],allowed_networks=plan['allowed_networks'])
        tls = {'cert_reqs':'CERT_REQUIRED','ca_certs':plan['ca_bundle'] or None} if scheme == 'https' else {}
        return pools[scheme](host,port,timeout=Timeout(connect=2,read=2),maxsize=4,block=True,**tls)
    except Exception:
        raise MonitoringError('source_network_policy_rejected') from None


def query(pool,plan,expression,at):
    token = os.environ.get(plan['token_env'],'')
    if not token or len(token) > 8192 or '\n' in token or '\r' in token:
        raise MonitoringError('source_credentials_unavailable')
    response = None
    try:
        deadline = time.monotonic()+5
        response = pool.urlopen('GET','/api/v1/query?'+urlencode({'query':expression,'time':at.timestamp(),'timeout':'2s'}),headers={'Accept':'application/json','Authorization':'Bearer '+token},redirect=False,retries=False,preload_content=False)
        if response.status in (401,403):
            raise MonitoringError('source_identity_rejected')
        if response.status != 200 or response.headers.get('Content-Encoding','identity') not in ('','identity'):
            raise MonitoringError('source_response_rejected')
        chunks = []; size = 0
        while True:
            if time.monotonic() > deadline:
                raise MonitoringError('source_timeout')
            chunk = response.read1(min(8192,524289-size),decode_content=False)
            if not chunk: break
            size += len(chunk)
            if size > 524288: raise MonitoringError('source_response_too_large')
            chunks.append(chunk)
        raw = b''.join(chunks)
        data = json.loads(raw,parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
        if data.get('status') != 'success' or data.get('data',{}).get('resultType') != 'vector' or data.get('warnings') or data.get('infos'):
            raise MonitoringError('source_response_rejected')
        return data['data']['result']
    except MonitoringError:
        raise
    except Exception:
        raise MonitoringError('source_request_failed') from None
    finally:
        if response is not None:
            response.close()
            response.release_conn()


def parse_vector(rows,name,plan,node_ids,*,timestamps=False):
    if not isinstance(rows,list) or len(rows) > 500:
        raise MonitoringError('source_response_rejected')
    result = {}
    for row in rows:
        try:
            labels = row['metric']; pair = row['value']
            if not isinstance(labels,dict) or any(labels.get(key) != value for key,value in plan['expected_labels'].items()):
                raise MonitoringError('source_scope_mismatch')
            node_id = labels.get('bluedrive_node_id')
            if name in NODE_METRICS:
                node_id = str(uuid.UUID(node_id))
                if node_id not in node_ids:
                    raise MonitoringError('source_node_unavailable')
                identity = node_id
            else:
                if node_id is not None:
                    raise MonitoringError('source_result_ambiguous')
                identity = 'cluster'
            if not isinstance(pair,list) or len(pair) != 2 or not isinstance(pair[1],str) or len(pair[1]) > 64:
                raise ValueError
            value = float(pair[1])
            if not math.isfinite(value) or (not timestamps and not valid_value(name,value)):
                raise ValueError
            if identity in result:
                raise MonitoringError('source_result_ambiguous')
            result[identity] = value
        except MonitoringError:
            raise
        except (KeyError,ValueError,TypeError,AttributeError):
            raise MonitoringError('source_response_rejected') from None
    return result


def fetch_metrics(plan,node_ids,now=None):
    at = now or timezone.now()
    pool = make_pool(plan)
    executor = ThreadPoolExecutor(max_workers=4)
    pending = {}; results = {}
    try:
        for name,spec in plan['queries'].items():
            for field in ('expr','timestamp_expr'):
                pending[executor.submit(query,pool,plan,spec[field],at)] = (name,field)
        for future in as_completed(pending,timeout=25):
            name,field = pending[future]
            results[(name,field)] = parse_vector(future.result(),name,plan,node_ids,timestamps=field == 'timestamp_expr')
        metrics = {}; nodes = {}; observed = []
        for name in plan['queries']:
            values = results[(name,'expr')]; stamps = results[(name,'timestamp_expr')]
            if set(values) != set(stamps) or (name in CLUSTER_METRICS and set(values) != {'cluster'}):
                raise MonitoringError('source_samples_missing')
            for identity,value in values.items():
                timestamp = stamps[identity]
                if timestamp > at.timestamp()+5 or timestamp < at.timestamp()-plan['stale_after_seconds']:
                    raise MonitoringError('source_samples_stale')
                observed.append(datetime.fromtimestamp(timestamp,datetime_timezone.utc))
                if name in CLUSTER_METRICS:
                    metrics[name] = value
                else:
                    nodes.setdefault(identity,{})[name] = value
        if not REQUIRED <= set(metrics):
            raise MonitoringError('source_samples_missing')
        if 'usable_free_bytes' in metrics and 'usable_capacity_bytes' in metrics and metrics['usable_free_bytes'] > metrics['usable_capacity_bytes']:
            raise MonitoringError('source_values_inconsistent')
        return {'cluster_metrics':metrics,'node_metrics':nodes},min(observed)
    except FutureTimeout:
        raise MonitoringError('source_timeout') from None
    except MonitoringError:
        raise
    except Exception:
        raise MonitoringError('source_request_failed') from None
    finally:
        executor.shutdown(wait=True,cancel_futures=True)
        pool.close()
