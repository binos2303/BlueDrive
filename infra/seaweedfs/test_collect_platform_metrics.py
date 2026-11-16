"""Tests riêng cho host collector; không cần Docker daemon hoặc Django."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name('collect-platform-metrics.py')
spec = importlib.util.spec_from_file_location('bluedrive_platform_metrics_collector', SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class DockerMetricParserTests(unittest.TestCase):
    def test_memory_network_and_cpu_units(self):
        self.assertEqual(collector.parse_bytes('1.5GiB'), 1610612736)
        self.assertEqual(collector.parse_bytes('23.2kB'), 23200)
        self.assertEqual(collector.parse_pair('3MiB / 1GiB'), (3145728, 1073741824))
        self.assertIsNone(collector.parse_bytes('secret'))
        self.assertEqual(collector.parse_cpu('13.20%'), 13.20)
        self.assertIsNone(collector.parse_cpu('-2%'))

    def test_df_is_filesystem_behind_data_mount(self):
        output = 'Filesystem 1024-blocks Used Available Capacity Mounted on\noverlay 400000 120000 280000 30% /data\n'
        self.assertEqual(collector.parse_df(output), (409600000, 286720000))
        self.assertEqual(collector.parse_df('not supported'), (None, None))

    def test_collect_only_approved_running_containers(self):
        safe = 'bluedrive-seaweedfs-volume-1'
        unknown = 'bluedrive-seaweedfs-fake-1'
        def docker(*args, required=True):
            if args[0] == 'ps':
                return safe + '\n' + unknown + '\n'
            if args[0] == 'stats':
                self.assertEqual(args[-1], safe)
                return json.dumps({'Name': safe, 'CPUPerc': '2.00%',
                                   'MemUsage': '1MiB / 2GiB', 'NetIO': '1kB / 2kB'})
            if args[0] == 'inspect':
                return '"healthy"\n'
            if args[0] == 'exec':
                return 'Filesystem 1024-blocks Used Available Capacity Mounted on\noverlay 100 20 80 20% /data\n'
            raise AssertionError(args)
        with patch.object(collector, 'docker', side_effect=docker), patch.object(collector, 'extra_names', return_value=set()):
            report = collector.collect()
        self.assertEqual(set(report['containers']), {'volume'})
        self.assertEqual(report['containers']['volume']['disk_available_bytes'], 81920)
        self.assertEqual(report['containers']['volume']['cpu_percent'], 2.0)

    def test_atomic_snapshot_and_no_secret_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'platform-metrics.json'
            with patch.object(collector, 'LOCAL', Path(tmp)), patch.object(collector, 'DEST', output):
                collector.write_sample({'schema': 1, 'sampled_at': '2026-11-13T00:00:00+00:00', 'containers': {}})
                self.assertEqual(json.loads(output.read_text())['schema'], 1)
                self.assertFalse(list(Path(tmp).glob('*.tmp')))


if __name__ == '__main__':
    unittest.main()
