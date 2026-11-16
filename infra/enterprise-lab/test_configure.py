"""Kiểm tra enterprise lab tạo môi trường riêng, không đụng cấu hình Platform."""
import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from configure import configure, validate_lab_database_target


class EnterpriseLabConfigTests(unittest.TestCase):
    def test_bootstrap_and_filer_use_enterprise_postgres_only(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            target = Path(temporary)
            template = Path(__file__).with_name('.env.example')
            (target / '.env.example').write_bytes(template.read_bytes())
            validate_lab_database_target(target)
            result = configure(target)
            self.assertEqual(result['FILER_DB_HOST'], 'postgres')
            self.assertGreaterEqual(len(result['POSTGRES_SUPERUSER_PASSWORD']), 20)
            self.assertNotEqual(result['POSTGRES_SUPERUSER_PASSWORD'], result['FILER_DB_PASSWORD'])
            filer = tomllib.loads((target / '.local/filer.toml').read_text(encoding='utf-8'))
            self.assertEqual(filer['postgres']['hostname'], 'postgres')
            self.assertEqual(filer['postgres']['database'], 'seaweedfs_enterprise_meta')
            self.assertFalse(filer['postgres']['createTable'])
            identities = json.loads((target / '.local/s3.json').read_text(encoding='utf-8'))['identities']
            self.assertEqual(len(identities), 2)
            self.assertNotEqual(identities[0]['credentials'], identities[1]['credentials'])
            self.assertNotIn('DROP ', (target / '.local/bootstrap.sql').read_text())
            original = (target / '.env').read_bytes()
            with self.assertRaises(ValueError):
                configure(target)
            self.assertEqual(original, (target / '.env').read_bytes())

    def test_wrong_database_host_fails_before_creating_secrets(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            target = Path(temporary)
            (target / '.env.example').write_bytes(Path(__file__).with_name('.env.example').read_bytes())
            (target / '.env').write_text('FILER_DB_HOST=host.docker.internal\n')
            with self.assertRaises(ValueError):
                validate_lab_database_target(target)
            self.assertFalse((target / '.local').exists())


if __name__ == '__main__':
    unittest.main()
