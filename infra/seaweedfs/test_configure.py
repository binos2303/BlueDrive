import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from configure import configure


class ConfigureTests(unittest.TestCase):
    def test_private_config_uses_separate_role_authenticated_bucket_scoped_identity(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict("os.environ", {}, clear=True):
            path = Path(temporary)
            (path / ".env.example").write_text(Path(__file__).with_name(".env.example").read_text(encoding="utf-8"), encoding="utf-8")
            config = configure(path)
            filer = tomllib.loads((path / ".local/filer.toml").read_text(encoding="utf-8"))
            self.assertTrue(filer["postgres"]["enabled"])
            self.assertFalse(filer["leveldb2"]["enabled"])
            self.assertFalse(filer["postgres"]["createTable"])
            self.assertEqual(filer["postgres"]["hostname"], "postgres")
            self.assertEqual(filer["postgres"]["port"], 5432)
            self.assertEqual([name for name, store in filer.items() if store.get("enabled")], ["postgres"])
            self.assertGreaterEqual(len(config["POSTGRES_SUPERUSER_PASSWORD"]), 20)
            self.assertNotEqual(config["POSTGRES_SUPERUSER_PASSWORD"], config["FILER_DB_PASSWORD"])
            identities = json.loads((path / ".local/s3.json").read_text(encoding="utf-8"))["identities"]
            self.assertEqual(len(identities), 2)
            self.assertNotEqual(identities[0]["credentials"], identities[1]["credentials"])
            self.assertTrue(all(action.endswith(":" + config["SEAWEED_S3_BUCKET"]) for action in identities[1]["actions"]))
            sql = (path / ".local/bootstrap.sql").read_text(encoding="utf-8")
            self.assertIn("NOSUPERUSER NOCREATEDB NOCREATEROLE", sql)
            self.assertIn('CREATE DATABASE "seaweedfs_meta" OWNER "seaweedfs_filer";', sql)
            self.assertIn("CREATE TABLE filemeta", sql)
            self.assertIn("PRIMARY KEY (dirhash, name)", sql)
            self.assertNotIn("DROP", sql)
            original = (path / ".env").read_bytes()
            with self.assertRaises(ValueError):
                configure(path)
            self.assertEqual((path / ".env").read_bytes(), original)

    def test_rejects_application_database_and_wildcard_origins_before_writing(self):
        for key, value in (("FILER_DB_NAME", "bluedrive_db"), ("FRONTEND_ORIGINS", "*"),
                           ("FILER_DB_HOST", "host.docker.internal"), ("FILER_DB_PORT", "5433")):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary, patch.dict("os.environ", {key: value}, clear=True):
                path = Path(temporary)
                (path / ".env.example").write_bytes(Path(__file__).with_name(".env.example").read_bytes())
                with self.assertRaises(ValueError):
                    configure(path)
                self.assertFalse((path / ".local").exists())

    def test_rejects_reused_admin_password_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict("os.environ", {
            "FILER_DB_PASSWORD": "test-only-same-password-12345",
            "POSTGRES_SUPERUSER_PASSWORD": "test-only-same-password-12345",
        }, clear=True):
            path = Path(temporary)
            (path / ".env.example").write_bytes(Path(__file__).with_name(".env.example").read_bytes())
            with self.assertRaises(ValueError):
                configure(path)
            self.assertFalse((path / ".local").exists())
