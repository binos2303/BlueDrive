"""Live dashboard: chỉ đưa ra dữ liệu Master thực tế và giữ quyền Platform."""
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase, override_settings
from infrastructure.platform_live import parse_topology, _stored_volume_bytes
from infrastructure.tests import InventoryFixture


class TopologyParserTests(SimpleTestCase):
    def test_node_slots_and_missing_nodes_are_reported_without_fake_capacity(self):
        result = parse_topology({'Topology': {'DataCenters': [{'Id': 'platform', 'Racks': [{'Id': 'lab',
            'DataNodes': [{'Url': 'volume:8080', 'Free': 28, 'Max': 32, 'Volumes': 4},
                          {'Url': 'volume2:8080', 'Free': 32, 'Max': 32, 'Volumes': 0}]}]}]}})
        self.assertEqual([node['online'] for node in result], [True, True, False])
        self.assertEqual(result[0]['free_slots'], 28)
        self.assertEqual(result[2]['max_slots'], 0)

    def test_volume_bytes_are_extracted_only_for_expected_servers(self):
        data = {'Volumes': {'DataCenters': {'platform': {'lab': {
            'volume:8080': [{'Id': 1, 'Size': 1048576}],
            'untrusted:8080': [{'Id': 10, 'Size': 9999999}],
        }}}}}
        self.assertEqual(_stored_volume_bytes(data)['volume'], 1048576)
        self.assertEqual(_stored_volume_bytes(data)['volume2'], 0)

    def test_free_slots_derived_when_master_omits_free(self):
        result = parse_topology({'Topology': {'DataCenters': [{'Racks': [{'DataNodes': [
            {'Url': 'volume:8080', 'Max': 32, 'Volumes': 21}]}]}]}})
        self.assertEqual(result[0]['free_slots'], 11)

    def test_unexpected_node_is_not_exposed(self):
        result = parse_topology({'Topology': {'DataCenters': [{'Racks': [{'DataNodes': [
            {'Url': 'external-host:8080', 'Free': 99, 'Max': 99}]}]}]}})
        self.assertFalse(any(node['online'] for node in result))


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True)
class PlatformLiveApiTests(InventoryFixture, TestCase):
    def test_platform_only_and_authenticated(self):
        endpoint = self.path('platform/live/', platform=True)
        self.client.logout()
        self.assertIn(self.client.get(endpoint).status_code, (401, 403))
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(endpoint).status_code, 404)
        self.client.force_login(self.root)
        with patch('infrastructure.api.read_platform_status', return_value={
            'master_online': True, 'nodes': [], 'online_nodes': 0, 'volume_slots': 0,
            'free_slots': 0, 'used_volume_slots': 0, 'source': 'seaweedfs_master',
            'physical_disk_bytes_available': None,
        }):
            response = self.client.get(endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['binding_ready'])
        self.assertNotIn('secret', response.content.decode())


class AddedNodeRegistryTests(SimpleTestCase):
    def test_extra_node_is_visible_after_registration_and_offline_when_absent(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from infrastructure.platform_live import parse_topology, _stored_volume_bytes

        with TemporaryDirectory() as tmp:
            base = Path(tmp) / 'backend'
            base.mkdir()
            local = Path(tmp) / 'infra' / 'seaweedfs' / '.local'
            local.mkdir(parents=True)
            (local / 'platform-nodes.json').write_text('{"extra_nodes":["volume4"]}', encoding='utf-8')
            with override_settings(BASE_DIR=base):
                topo = parse_topology({'Topology': {'DataCenters': [{'Id': 'platform', 'Racks': [{'Id': 'lab',
                    'DataNodes': [{'Url': 'volume4:8080', 'Free': 32, 'Max': 32, 'Volumes': 0}]}]}]}})
                self.assertEqual([n['id'] for n in topo], ['volume', 'volume2', 'volume3', 'volume4'])
                self.assertTrue(topo[-1]['online'])
                stored = _stored_volume_bytes({'Volumes': {'DataCenters': {'platform': {'lab': {
                    'volume4:8080': [{'Id': 23, 'Size': 1024}],
                }}}}})
                self.assertEqual(stored['volume4'], 1024)
                offline = parse_topology({'Topology': {'DataCenters': []}})
                self.assertFalse(offline[-1]['online'])

    def test_unapproved_node_name_in_registry_is_ignored(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from infrastructure.platform_live import expected_nodes

        with TemporaryDirectory() as tmp:
            base = Path(tmp) / 'backend'
            base.mkdir()
            local = Path(tmp) / 'infra' / 'seaweedfs' / '.local'
            local.mkdir(parents=True)
            (local / 'platform-nodes.json').write_text('{"extra_nodes":["evil-host","volume13","volume4"]}', encoding='utf-8')
            with override_settings(BASE_DIR=base):
                self.assertEqual(expected_nodes(), ('volume', 'volume2', 'volume3', 'volume4'))

class PlatformResourceMonitoringTests(SimpleTestCase):
    def test_fresh_docker_sample_is_allowlisted_and_stale_samples_are_not_served(self):
        import json
        from datetime import timedelta
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from django.utils import timezone
        from infrastructure.platform_live import _read_docker_metrics

        with TemporaryDirectory() as tmp:
            base = Path(tmp) / 'backend'
            base.mkdir()
            local = Path(tmp) / 'infra' / 'seaweedfs' / '.local'
            local.mkdir(parents=True)
            path = local / 'platform-metrics.json'
            data = {'schema': 1, 'source': 'docker_cli', 'sampled_at': timezone.now().isoformat(),
                    'containers': {
                        'volume': {'running': True, 'docker_health': 'healthy', 'cpu_percent': 2.5,
                                   'memory_used_bytes': 4096, 'memory_limit_bytes': 8192,
                                   'disk_total_bytes': 10240, 'disk_available_bytes': 5120},
                        'unapproved-container': {'running': True, 'docker_health': 'healthy', 'cpu_percent': 99},
                    }}
            with override_settings(BASE_DIR=base):
                path.write_text(json.dumps(data), encoding='utf-8')
                fresh = _read_docker_metrics()
                self.assertEqual(fresh['state'], 'fresh')
                self.assertEqual(set(fresh['containers']), {'volume'})
                self.assertEqual(fresh['containers']['volume']['cpu_percent'], 2.5)
                data['sampled_at'] = (timezone.now() - timedelta(minutes=3)).isoformat()
                path.write_text(json.dumps(data), encoding='utf-8')
                stale = _read_docker_metrics()
                self.assertEqual(stale['state'], 'stale')
                self.assertFalse(stale['containers'])
                data['sampled_at'] = timezone.now().isoformat()
                data['containers']['volume']['cpu_percent'] = -1
                path.write_text(json.dumps(data), encoding='utf-8')
                self.assertIsNone(_read_docker_metrics()['containers']['volume']['cpu_percent'])

    def test_alerts_only_use_observed_failures_and_do_not_aggregate_shared_disk(self):
        from infrastructure.platform_live import build_platform_alerts
        report = {
            'master_online': True, 's3_gateway_responding': False,
            'nodes': [{'id': 'volume', 'online': True}, {'id': 'volume2', 'online': False}],
            'routing_enabled': True, 'binding_ready': False,
            'docker_metrics': {'state': 'fresh', 'containers': {
                'volume': {'docker_health': 'unhealthy', 'disk_total_bytes': 1000,
                           'disk_available_bytes': 50}}}}
        codes = [a['code'] for a in build_platform_alerts(report)]
        self.assertIn('node_unregistered', codes)
        self.assertIn('s3_probe_failed', codes)
        self.assertIn('routing_without_binding', codes)
        self.assertIn('docker_unhealthy', codes)
        self.assertEqual(codes.count('filesystem_pressure'), 1)
        report['docker_metrics']['state'] = 'stale'
        self.assertNotIn('filesystem_pressure', [a['code'] for a in build_platform_alerts(report)])

    def test_collection_inventory_distinguishes_unique_volume_ids_and_copies(self):
        from infrastructure.platform_live import _collection_inventory
        sample = {'Volumes': {'DataCenters': {'platform': {'lab': {
            'volume:8080': [{'Collection': 'bluedrive-dev', 'Id': 5, 'Size': 100},
                            {'Collection': 'bluedrive-dev', 'Id': 6, 'Size': 200}],
            'volume2:8080': [{'Collection': 'bluedrive-dev', 'Id': 5, 'Size': 100}],
            'evil:8080': [{'Collection': 'secret', 'Id': 9, 'Size': 99}],
        }}}}}
        rows = _collection_inventory(sample)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['unique_volumes'], 2)
        self.assertEqual(rows[0]['volume_copies'], 3)
        self.assertEqual(rows[0]['stored_bytes'], 400)
