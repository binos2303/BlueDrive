"""Kiểm tra chống lộ secret bằng fixture giả trong Git repository tạm."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_repository_safety import audit, audit_history, git, scan_text


class RepositorySafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run_git("init", "--quiet")

    def run_git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_ignored_private_env_is_not_read_and_safe_template_passes(self):
        self.write(".gitignore", ".env\n")
        self.write(".env", "DB_PASSWORD=private-local-value\n")
        self.write(".env.example", "DB_PASSWORD=\nSECRET_KEY=<set-in-runtime>\nDB_HOST=localhost\n")
        original = Path.read_bytes

        def guarded_read(path):
            self.assertNotEqual(path.name, ".env")
            return original(path)

        with patch.object(Path, "read_bytes", guarded_read):
            self.assertEqual(audit(self.root)["status"], "PASS")

    def test_force_added_private_artifact_fails_before_reading(self):
        self.write(".env", "DB_PASSWORD=private-local-value\n")
        self.run_git("add", ".env")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Must not read private file")):
            report = audit(self.root)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["findings"], [{"path": ".env", "line": 0, "kind": "private-artifact"}])

    def test_index_is_checked_when_worktree_has_removed_the_token(self):
        fake = "ghp_" + "A" * 36
        self.write("client.py", f'value = "{fake}"\n')
        self.run_git("add", "client.py")
        self.write("client.py", "value = None\n")
        self.assertEqual(audit(self.root)["status"], "PASS")
        report = audit(self.root, staged=True)
        self.assertEqual(report["status"], "FAIL")
        self.assertNotIn(fake, json.dumps(report))

    def test_dummy_password_does_not_hide_real_token_pattern_in_test_source(self):
        self.assertEqual(scan_text("tests/test_api.py", 'password = "fixture-only-password"'), [])
        fake = "sk-proj-" + "B" * 40
        self.assertTrue(scan_text("tests/test_api.py", f'token = "{fake}"'))
        self.assertTrue(scan_text("settings.py", 'DB_PASSWORD = "hardcoded-runtime-value"'))
        self.assertTrue(scan_text(".env.example", "DB_PASSWORD=hardcoded-runtime-value"))
        self.assertTrue(scan_text("settings.py", 'PASSWORD = "password"'))
        self.assertTrue(scan_text(".env.example", "DB_PASSWORD=test"))
        dummy_url = "https://user:" + "secret@storage.invalid"
        self.assertEqual(scan_text("tests/test_url.py", dummy_url), [])
        self.assertTrue(scan_text("settings.py", dummy_url))
        self.assertTrue(scan_text("tests/test_url.py", "https://user:" + "runtime-value@storage.invalid"))

    def test_urls_private_keys_and_dump_headers_are_detected_without_values(self):
        signed = "https://storage.invalid/object?X-Amz-" + "Signature=" + "a" * 64
        private = "-----BEGIN " + "PRIVATE KEY-----"
        dsn = "postgresql://user:" + "runtime-value@db.invalid/app"
        for content, kind in ((signed, "signed-url"), (private, "private-key"),
                              (dsn, "url-password"), ("-- PostgreSQL database dump", "database-dump")):
            with self.subTest(kind=kind):
                report = scan_text("source.txt", content)
                self.assertIn(kind, [item["kind"] for item in report])
                self.assertNotIn(content, json.dumps(report))

    def test_compose_env_reference_is_allowed_but_literal_password_is_not(self):
        self.assertEqual(scan_text("compose.yml", "  MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:?Set locally}"), [])
        self.assertTrue(scan_text("compose.yml", "  MINIO_ROOT_PASSWORD: runtime-value"))

    def test_form_labels_and_cli_examples_are_not_runtime_assignments(self):
        self.assertEqual(scan_text("views.py", '    "old_password": "Current password",'), [])
        self.assertEqual(scan_text("cli-help.txt", '    "secretKey": "some example key"'), [])
        self.assertTrue(scan_text("settings.py", 'OLD_PASSWORD = "hardcoded-runtime-value"'))
        self.assertTrue(scan_text("config.json", '    "secretKey": "hardcoded-runtime-value"'))

    def test_private_paths_are_blocked_without_confusing_backup_ui_routes(self):
        for name in ("backups/db.sql", "DATA.DUMP", "TLS.KEY", "infra/seaweedfs/.local/filer.toml", "frontend/playwright/.auth/user.json"):
            self.write(name, "private-local-value")
        self.write("frontend/app/admin/backups/page.tsx", "export default function Page() {}")
        report = audit(self.root)
        self.assertEqual(len(report["findings"]), 5)
        self.assertNotIn("frontend/app/admin/backups/page.tsx", [item["path"] for item in report["findings"]])

    def test_unreadable_source_is_blocked_instead_of_false_pass(self):
        self.write("client.py", "value = None\n")
        with patch.object(Path, "read_bytes", side_effect=PermissionError):
            self.assertEqual(audit(self.root)["status"], "BLOCKED")

    def test_unrelated_binary_is_reported_as_unscanned(self):
        (self.root / "asset.bin").write_bytes(b"\0\x01\x02")
        report = audit(self.root)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["binary_files_not_scanned"], 1)

    def commit_fixture(self):
        # Chỉ tạo commit synthetic trong TemporaryDirectory, không đụng Git của dự án.
        self.run_git("add", ".")
        self.run_git("-c", "user.name=Safety Fixture", "-c", "user.email=fixture@example.invalid",
                     "-c", "core.hooksPath=", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
        return git(self.root, "rev-parse", "HEAD").decode().strip()

    def test_history_detects_removed_token_and_can_limit_to_clean_ref(self):
        self.write("client.py", "value = None\n")
        clean_ref = self.commit_fixture()
        fake = "ghp_" + "A" * 36
        self.write("client.py", f'value = "{fake}"\n')
        self.commit_fixture()
        self.write("client.py", "value = None\n")
        self.commit_fixture()
        self.assertEqual(audit(self.root, staged=True)["status"], "PASS")
        report = audit_history(self.root)
        self.assertEqual(report["status"], "FAIL")
        self.assertNotIn(fake, json.dumps(report))
        self.assertEqual(audit_history(self.root, ref=clean_ref)["status"], "PASS")

    def test_history_does_not_read_private_blob_through_public_alias(self):
        self.write(".env", "private-fixture-value")
        self.write("public.py", "private-fixture-value")
        self.commit_fixture()
        with patch("check_repository_safety.git", wraps=git) as operations:
            report = audit_history(self.root)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["findings"][0]["path"], ".env")
        self.assertFalse(any("cat-file" in call.args for call in operations.call_args_list))

    def test_empty_history_is_blocked_instead_of_zero_scope_pass(self):
        self.assertEqual(audit_history(self.root)["status"], "BLOCKED")

    def test_ci_test_password_expression_does_not_allow_literal_or_arbitrary_expressions(self):
        for value in (
            "${{ github.run_id }}-${{ github.run_attempt }}",
            "${BLUEDRIVE_TEST_DB_PASSWORD:?Set a separate test password}",
        ):
            with self.subTest(value=value):
                self.assertEqual(scan_text(".github/workflows/verify.yml", f"POSTGRES_PASSWORD: {value}"), [])
        for value in ("fixed-password", "${{ 'fixed-password' }}", "${{ github.run_id }}-fixed-password"):
            with self.subTest(value=value):
                findings = scan_text(".github/workflows/verify.yml", f"POSTGRES_PASSWORD: {value}")
                self.assertEqual([item["kind"] for item in findings], ["credential-literal"])
