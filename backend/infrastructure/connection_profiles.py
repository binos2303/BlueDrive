"""Profile do operator cấp; browser không được chỉ định URL, CIDR hoặc secret."""
import hashlib
import ipaddress
import json
import os
import re
import socket
from urllib.parse import urlsplit

import boto3
from botocore.awsrequest import AWSHTTPConnection, AWSHTTPSConnection, AWSHTTPConnectionPool, AWSHTTPSConnectionPool
from botocore.config import Config
from django.conf import settings
from urllib3.exceptions import NewConnectionError
from urllib3.util.connection import create_connection

from files.storage_adapters.base import StorageConfigurationError


class ProfileUnavailable(StorageConfigurationError):
    pass


def origin(value, *, lab=False):
    try:
        parsed = urlsplit(value)
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        host = parsed.hostname
        if not isinstance(value, str) or len(value) > 512 or not host or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/') or any(c.isspace() for c in value):
            raise ValueError
        if not re.fullmatch(r'[a-zA-Z0-9.:-]+', host) or not 1 <= port <= 65535:
            raise ValueError
        local = host in {'localhost','127.0.0.1','::1'} or host.endswith('.localhost')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and lab and settings.DEBUG and local):
            raise ValueError
        return (parsed.scheme, host.lower(), port)
    except (ValueError, TypeError, AttributeError):
        raise ProfileUnavailable('Storage connection profile is unavailable.') from None


def _public_isolated(value, lab):
    scheme, host, port = origin(value, lab=lab)
    app_hosts = {urlsplit(value).hostname for value in settings.CORS_ALLOWED_ORIGINS}
    app_hosts.update(value.lstrip('.') for value in settings.ALLOWED_HOSTS if value != '*')
    if host in app_hosts:
        raise ProfileUnavailable('Storage browser endpoint must be cookie-isolated.')
    for domain in (settings.SESSION_COOKIE_DOMAIN, settings.CSRF_COOKIE_DOMAIN):
        if domain and (host == domain.lstrip('.').lower() or host.endswith('.' + domain.lstrip('.').lower())):
            raise ProfileUnavailable('Storage browser endpoint must be cookie-isolated.')
    return (scheme,host,port)


def _address_allowed(address, networks, *, lab):
    try:
        ip = ipaddress.ip_address(address)
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved or (ip.is_loopback and not (lab and settings.DEBUG)):
            return False
        return any(ip in network for network in networks)
    except ValueError:
        return False


def resolve_addresses(endpoint, allowed_networks, lab):
    scheme, host, port = origin(endpoint, lab=lab)
    try:
        networks = [ipaddress.ip_network(value, strict=True) for value in allowed_networks]
        addresses = sorted({str(ipaddress.ip_address(record[4][0])) for record in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
        if not addresses or any(not _address_allowed(value, networks, lab=lab) for value in addresses):
            raise ValueError
        if scheme == 'http' and any(not ipaddress.ip_address(value).is_loopback for value in addresses):
            raise ValueError
        return addresses
    except (ValueError, TypeError, OSError):
        raise ProfileUnavailable('Storage endpoint is not within its approved network policy.') from None


def profiles_for(tenant_id):
    registry = settings.SECUREDRIVE_STORAGE_CONNECTION_PROFILES
    if not isinstance(registry, dict) or len(registry) > 100:
        raise ProfileUnavailable('Storage connection profile registry is unavailable.')
    scope = 'platform' if tenant_id is None else 'organization'
    return {key:value for key,value in registry.items() if isinstance(key,str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}',key) and isinstance(value,dict) and value.get('scope') == scope and (value.get('tenant_id') in (None,'') if tenant_id is None else value.get('tenant_id') == str(tenant_id))}


def profile_spec(profile_id, tenant_id, *, resolve=False):
    profile = profiles_for(tenant_id).get(profile_id)
    allowed = {'scope','tenant_id','label','provider','edition','provider_version','endpoint_url','public_endpoint_url','bucket','region','allowed_networks','access_key_env','secret_key_env','lab','ca_bundle','server_side_encryption','kms_key_id'}
    if profile is None or set(profile) - allowed:
        raise ProfileUnavailable('Storage connection profile is unavailable.')
    try:
        lab = profile.get('lab', False)
        if type(lab) is not bool or profile.get('provider') != 's3':
            raise ValueError
        endpoint = profile['endpoint_url'].rstrip('/')
        public = profile['public_endpoint_url'].rstrip('/')
        origin(endpoint, lab=lab)
        _public_isolated(public, lab)
        bucket = profile['bucket']
        if not isinstance(bucket,str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',bucket) or bucket.startswith('bluedrive-scc-') or '..' in bucket:
            raise ValueError
        networks = profile['allowed_networks']
        if not isinstance(networks,list) or not 1 <= len(networks) <= 16:
            raise ValueError
        for network in networks:
            ipaddress.ip_network(network,strict=True)
        for field in ('access_key_env','secret_key_env'):
            if not isinstance(profile[field],str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{1,127}',profile[field]):
                raise ValueError
        sse = profile.get('server_side_encryption','')
        if sse not in {'','AES256','aws:kms'} or (not sse and not (lab and settings.DEBUG)) or (sse == 'aws:kms' and not profile.get('kms_key_id')):
            raise ValueError
        if not isinstance(profile.get('region','us-east-1'),str) or not re.fullmatch(r'[a-z0-9-]{1,63}',profile.get('region','us-east-1')):
            raise ValueError
        for field, maximum in (('label',200),('edition',80),('provider_version',100),('region',64),('ca_bundle',1024),('kms_key_id',255)):
            if not isinstance(profile.get(field,''),str) or len(profile.get(field,'')) > maximum:
                raise ValueError
        spec = {'endpoint_url':endpoint,'public_endpoint_url':public,'bucket':bucket,
                'region':profile.get('region','us-east-1'),'access_key_env':profile['access_key_env'],
                'secret_key_env':profile['secret_key_env'],'allowed_networks':networks,
                'ca_bundle':profile.get('ca_bundle',''),'server_side_encryption':sse,
                'kms_key_id':profile.get('kms_key_id',''),'lab':lab}
        spec['profile_digest'] = hashlib.sha256(json.dumps({'scope':profile['scope'],'tenant_id':profile.get('tenant_id'),**spec},sort_keys=True).encode()).hexdigest()
        if resolve:
            spec['resolved_ips'] = resolve_addresses(endpoint,networks,lab)
        return spec
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ProfileUnavailable('Storage connection profile is unavailable.') from None


def public_profile(profile_id, tenant_id):
    profile_spec(profile_id,tenant_id)
    data = profiles_for(tenant_id)[profile_id]
    return {'id':profile_id,'label':data.get('label',profile_id),'endpoint_url':data['endpoint_url'],
            'public_endpoint_url':data['public_endpoint_url'],'provider':data['provider'],
            'edition':data.get('edition',''),'provider_version':data.get('provider_version',''),
            'lab':data.get('lab',False)}


def pinned_pool_classes(endpoint_url, addresses, *, lab, allowed_networks):
    expected = origin(endpoint_url,lab=lab)
    try:
        networks = [ipaddress.ip_network(value,strict=True) for value in allowed_networks]
        if not addresses or any(not _address_allowed(value,networks,lab=lab) for value in addresses):
            raise ValueError
    except (ValueError,TypeError):
        raise ProfileUnavailable('Pinned storage network policy is unavailable.') from None

    class PinnedSocket:
        def _new_conn(self):
            if self.host.lower() != expected[1] or self.port != expected[2] or getattr(self,'proxy',None) is not None:
                raise NewConnectionError(self,'Unapproved storage transport target.')
            for address in addresses:
                try:
                    # Giữ hostname/SNI ban đầu, chỉ thay đích socket bằng IP đã duyệt.
                    return create_connection((address,self.port),self.timeout,source_address=self.source_address,socket_options=self.socket_options)
                except OSError:
                    continue
            raise NewConnectionError(self,'Approved storage transport is unavailable.')

    class PinnedHTTP(PinnedSocket,AWSHTTPConnection):
        pass
    class PinnedHTTPS(PinnedSocket,AWSHTTPSConnection):
        pass
    class HTTPPool(AWSHTTPConnectionPool):
        ConnectionCls = PinnedHTTP
    class HTTPSPool(AWSHTTPSConnectionPool):
        ConnectionCls = PinnedHTTPS

    return {'http':HTTPPool,'https':HTTPSPool}


def bind_transport(client, endpoint_url, addresses, *, lab, allowed_networks):
    expected = origin(endpoint_url,lab=lab)
    pools = pinned_pool_classes(endpoint_url,addresses,lab=lab,allowed_networks=allowed_networks)

    def validate_request(request, **kwargs):
        if origin_for_request(request.url) != expected:
            raise ProfileUnavailable('Storage redirect target is not approved.')

    client.meta.events.register('before-send.s3', validate_request)
    client._endpoint.http_session._manager.pool_classes_by_scheme = pools
    return client


def origin_for_request(url):
    # URL SDK có path/query đã ký; kiểm origin mà không ghi URL vào lỗi.
    try:
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError
        return (parsed.scheme,parsed.hostname.lower(),parsed.port or (443 if parsed.scheme == 'https' else 80))
    except (ValueError,AttributeError):
        raise ProfileUnavailable('Unapproved storage request origin.') from None


def build_client(connection):
    access = os.environ.get(connection.access_key_env,'')
    secret = os.environ.get(connection.secret_key_env,'')
    if not access or not secret:
        raise ProfileUnavailable('Versioned storage credentials are unavailable.')
    client = boto3.client('s3',endpoint_url=connection.endpoint_url,region_name=connection.region,
                          aws_access_key_id=access,aws_secret_access_key=secret,
                          verify=connection.ca_bundle or True,
                          config=Config(signature_version='s3v4',s3={'addressing_style':'path'},
                                        connect_timeout=2,read_timeout=5,retries={'total_max_attempts':1},proxies={}))
    try:
        addresses = resolve_addresses(connection.endpoint_url,connection.allowed_networks,connection.lab)
        return bind_transport(client,connection.endpoint_url,addresses,lab=connection.lab,allowed_networks=connection.allowed_networks)
    except Exception:
        client.close()
        raise ProfileUnavailable('Pinned storage transport is unavailable.') from None
