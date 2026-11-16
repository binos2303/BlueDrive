"""Bảo đảm gate persistence không đọc hoặc dọn nhầm probe của đích khác."""
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import smoke


class RestartProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        (self.directory / ".env").touch()
        (self.directory / ".local").mkdir()
        (self.directory / ".local/cors.json").write_text("{}", encoding="utf-8")
        self.manifest = self.directory / ".local/restart-probe.json"
        self.payload = b"BlueDrive Task 01 restart persistence\n"
        self.probe = {"key": "primary/" + "a" * 32, "version_id": "probe-version",
            "bucket": "fixture-bucket", "endpoint": "http://127.0.0.1:8333",
            "size_bytes": len(self.payload), "sha256": hashlib.sha256(self.payload).hexdigest()}
        self.adapter = Mock()
        self.adapter.open_object.return_value = io.BytesIO(self.payload)
        self.enterContext(patch.dict(os.environ, {
            "SEAWEEDFS_ALLOW_TEST_WRITES": "1", "SEAWEED_S3_ENDPOINT": self.probe["endpoint"],
            "SEAWEED_S3_PUBLIC_ENDPOINT": "http://s3.localhost:8333", "SEAWEED_S3_BUCKET": self.probe["bucket"],
            "SEAWEED_S3_ACCESS_KEY": "test-key", "SEAWEED_S3_SECRET_KEY": "test-secret",
        }, clear=True))
        self.enterContext(patch.object(smoke, "load_dotenv"))
        self.enterContext(patch("builtins.print"))
        self.enterContext(patch.object(smoke, "S3CompatibleStorageAdapter", return_value=self.adapter))
        self.enterContext(patch.object(smoke.sys, "argv", ["smoke.py", "verify-restart", "--config-dir", str(self.directory)]))

    def test_matching_probe_cleans_only_the_verified_version(self):
        self.manifest.write_text(json.dumps(self.probe), encoding="utf-8")
        self.assertEqual(smoke.main(), 0)
        self.adapter.open_object.assert_called_once_with(self.probe["key"], version_id="probe-version")
        self.adapter._client.delete_object.assert_called_once_with(
            Bucket="fixture-bucket", Key=self.probe["key"], VersionId="probe-version")
        self.adapter.delete_object.assert_not_called()
        self.assertFalse(self.manifest.exists())

    def test_wrong_target_or_unpinned_manifest_is_retained_without_storage_io(self):
        for field, value in (("endpoint", "http://127.0.0.1:8433"), ("bucket", "other-bucket"),
                             ("version_id", ""), ("version_id", "null"), ("key", "primary/not-generated"),
                             ("sha256", "0" * 64), ("size_bytes", 0)):
            with self.subTest(field=field, value=value):
                probe = {**self.probe, field: value}
                self.manifest.write_text(json.dumps(probe), encoding="utf-8")
                with self.assertRaises(ValueError):
                    smoke.main()
                self.assertEqual(json.loads(self.manifest.read_text(encoding="utf-8")), probe)
                self.adapter.open_object.assert_not_called()
                self.adapter._client.delete_object.assert_not_called()

    def test_content_mismatch_preserves_probe_for_investigation(self):
        self.manifest.write_text(json.dumps(self.probe), encoding="utf-8")
        self.adapter.open_object.return_value = io.BytesIO(b"unexpected contents")
        with self.assertRaises(ValueError):
            smoke.main()
        self.assertTrue(self.manifest.exists())
        self.adapter._client.delete_object.assert_not_called()

    def test_failed_cleanup_keeps_manifest_for_retry(self):
        self.manifest.write_text(json.dumps(self.probe), encoding="utf-8")
        self.adapter._client.delete_object.side_effect = OSError("test-only cleanup failure")
        with self.assertRaises(OSError):
            smoke.main()
        self.assertTrue(self.manifest.exists())


if __name__ == "__main__":
    unittest.main()
