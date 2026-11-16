"""Chặn SSRF và giữ socket đúng IP đã duyệt, kể cả khi DNS đổi sau kiểm tra."""
import os
import datetime
import ssl
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from urllib3.exceptions import NewConnectionError
from urllib3.exceptions import SSLError as UrllibSSLError
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from infrastructure.connection_profiles import ProfileUnavailable, bind_transport, build_client, origin, resolve_addresses


class TransportSecurityTests(SimpleTestCase):
    def target(self):
        return SimpleNamespace(endpoint_url='https://storage.example.invalid',region='us-east-1',
            access_key_env='SCC_FIXTURE_ACCESS',secret_key_env='SCC_FIXTURE_SECRET',ca_bundle='',
            allowed_networks=['10.30.0.10/32'],lab=False)

    def test_metadata_and_mixed_dns_answers_are_rejected(self):
        for ips in (['169.254.169.254'],['10.30.0.10','127.0.0.1'],['10.30.0.10','10.30.0.11']):
            with self.subTest(ips=ips), patch('socket.getaddrinfo',return_value=[(2,1,6,'',(ip,443)) for ip in ips]):
                with self.assertRaises(ProfileUnavailable):
                    resolve_addresses('https://storage.example.invalid',['0.0.0.0/0'] if ips[0].startswith('169.') else ['10.30.0.10/32'],False)

    def test_http_only_allowed_in_debug_lab_loopback(self):
        with override_settings(DEBUG=False),self.assertRaises(ProfileUnavailable):
            origin('http://localhost:9000',lab=True)
        with override_settings(DEBUG=True):
            self.assertEqual(origin('http://objects.localhost:9000',lab=True),('http','objects.localhost',9000))
            with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('10.30.0.10',9000))]),self.assertRaises(ProfileUnavailable):
                resolve_addresses('http://objects.localhost:9000',['10.30.0.10/32'],True)

    def test_dns_rebinding_cannot_change_socket_or_redirect_origin(self):
        client = Mock()
        client._endpoint.http_session._manager = SimpleNamespace()
        bind_transport(client,'https://storage.example.invalid',['10.30.0.10'],lab=False,allowed_networks=['10.30.0.10/32'])
        guard = client.meta.events.register.call_args.args[1]
        guard(SimpleNamespace(url='https://storage.example.invalid/data?mock-signature'))
        for url in ('https://169.254.169.254/data','https://other.example.invalid/data','http://storage.example.invalid/data','https://storage.example.invalid:444/data'):
            with self.assertRaises(ProfileUnavailable):
                guard(SimpleNamespace(url=url))
        pool = client._endpoint.http_session._manager.pool_classes_by_scheme['https']
        connection = pool.ConnectionCls('storage.example.invalid',443,timeout=2)
        with patch('infrastructure.connection_profiles.create_connection') as connect,patch('socket.getaddrinfo',side_effect=AssertionError('No second DNS lookup for host')):
            connection._new_conn()
        self.assertEqual(connect.call_args.args[0],('10.30.0.10',443))
        self.assertEqual(connection.host,'storage.example.invalid','TLS hostname and SNI must retain the approved hostname')
        other = pool.ConnectionCls('other.example.invalid',443,timeout=2)
        with self.assertRaises(NewConnectionError):
            other._new_conn()

    def test_client_disables_proxies_requires_explicit_credentials_and_validates_tls(self):
        with patch.dict(os.environ,{'SCC_FIXTURE_ACCESS':'test-access','SCC_FIXTURE_SECRET':'test-secret'}),patch('infrastructure.connection_profiles.boto3.client') as factory,patch('infrastructure.connection_profiles.resolve_addresses',return_value=['10.30.0.10']):
            build_client(self.target())
        args = factory.call_args.kwargs
        self.assertIs(args['verify'],True)
        self.assertEqual(args['config'].proxies,{})
        self.assertEqual(args['config'].s3,{'addressing_style':'path'})
        with patch.dict(os.environ,{},clear=True),patch('infrastructure.connection_profiles.boto3.client') as factory,self.assertRaises(ProfileUnavailable):
            build_client(self.target())
        factory.assert_not_called()

    def test_dns_rejection_closes_constructed_sdk_client(self):
        with patch.dict(os.environ,{'SCC_FIXTURE_ACCESS':'test-access','SCC_FIXTURE_SECRET':'test-secret'}),patch('infrastructure.connection_profiles.boto3.client') as factory,patch('infrastructure.connection_profiles.resolve_addresses',side_effect=ProfileUnavailable('not approved')):
            with self.assertRaises(ProfileUnavailable):
                build_client(self.target())
        factory.return_value.close.assert_called_once()


@override_settings(DEBUG=True)
class PinnedTLSIntegrationTests(SimpleTestCase):
    """TLS server chỉ tồn tại trong test; không kết nối dịch vụ hoặc bucket thật."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='scc-tls-fixture-')
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'storage.example.invalid')])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('storage.example.invalid')]),critical=False).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(key,hashes.SHA256())
        self.ca = folder/'fixture-ca.pem'
        self.ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        pem = folder/'fixture-key.pem'
        pem.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        class Handler(BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.send_response(200)
                self.end_headers()
            def log_message(self,*args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.ca,pem)
        self.sni = []
        context.set_servername_callback(lambda socket,name,ctx: self.sni.append(name))
        self.server.socket = context.wrap_socket(self.server.socket,server_side=True)
        thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join,2)
        self.addCleanup(self.server.shutdown)

    def pool(self,host='storage.example.invalid',trusted=True):
        client = Mock()
        client._endpoint.http_session._manager = SimpleNamespace()
        bind_transport(client,f'https://{host}:{self.server.server_port}',['127.0.0.1'],lab=True,allowed_networks=['127.0.0.1/32'])
        cls = client._endpoint.http_session._manager.pool_classes_by_scheme['https']
        pool = cls(host,self.server.server_port,timeout=2,cert_reqs='CERT_REQUIRED',ca_certs=str(self.ca) if trusted else None)
        self.addCleanup(pool.close)
        return pool

    def test_real_tls_uses_pinned_ip_with_original_sni_and_trusted_certificate(self):
        with patch('socket.getaddrinfo',wraps=__import__('socket').getaddrinfo) as dns:
            response = self.pool().urlopen('HEAD','/',retries=False)
        self.assertEqual(response.status,200)
        self.assertEqual(self.sni,['storage.example.invalid'])
        self.assertTrue(all(call.args[0]=='127.0.0.1' for call in dns.call_args_list),'DNS must never resolve the approved hostname again inside the socket')

    def test_real_tls_rejects_untrusted_certificate_and_wrong_hostname(self):
        for host,trusted in (('storage.example.invalid',False),('wrong.example.invalid',True)):
            with self.subTest(host=host,trusted=trusted),self.assertRaises(UrllibSSLError):
                self.pool(host,trusted).urlopen('HEAD','/',retries=False)
