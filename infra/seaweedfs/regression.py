"""Test mặc định dùng settings/DB riêng; provider thật phải được opt-in tường minh."""
import argparse
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit


DEFAULT_LABELS = ["accounts", "dashboard", "files", "folders", "security", "sharing", "logs", "infrastructure"]
LIVE_CLASSES = {
    "files.tests.test_seaweedfs_integration": "SeaweedFSIntegrationTests",
    "files.tests.test_seaweedfs_finalizer_integration": "SeaweedFSFinalizerIntegrationTests",
}


def approved_live_labels(labels):
    """Module chỉ là alias cho class đã review; test mới trong module không tự được cấp quyền live."""
    approved = {module: module + "." + name for module, name in LIVE_CLASSES.items()}
    approved.update({label: label for label in list(approved.values())})
    if any(label not in approved for label in labels):
        raise ValueError("Live storage chỉ nhận hai provider integration classes đã duyệt.")
    return list(dict.fromkeys(approved[label] for label in labels))


def approved_live_environment(environment, scope):
    """Chỉ cấp credential S3 fixture; không kế thừa dotenv, media/email hoặc endpoint vận hành."""
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?", scope):
        raise ValueError("Scope live phải là định danh fixture chữ thường/số/gạch ngang, tối đa 32 ký tự.")
    if environment.get("SEAWEEDFS_ALLOW_TEST_WRITES") != "1":
        raise ValueError("Live storage cần SEAWEEDFS_ALLOW_TEST_WRITES=1 cho fixture riêng.")
    if environment.get("SEAWEED_S3_BUCKET") != "bluedrive-test-" + scope:
        raise ValueError("Bucket live phải khớp bluedrive-test-<scope>, không dùng bucket phục vụ.")
    keys = ("SEAWEED_S3_ENDPOINT", "SEAWEED_S3_PUBLIC_ENDPOINT", "SEAWEED_S3_BUCKET",
            "SEAWEED_S3_ACCESS_KEY", "SEAWEED_S3_SECRET_KEY")
    if any(not environment.get(key, "").strip() for key in keys):
        raise ValueError("Thiếu endpoint/credential fixture SeaweedFS; không dùng fallback runtime.")
    for key, hosts in (("SEAWEED_S3_ENDPOINT", {"127.0.0.1"}),
                       ("SEAWEED_S3_PUBLIC_ENDPOINT", {"127.0.0.1", "s3.localhost"})):
        try:
            parsed = urlsplit(environment[key])
            valid = (not any(character.isspace() for character in environment[key])
                     and parsed.scheme == "http" and parsed.hostname in hosts and parsed.port is not None
                     and 0 < parsed.port < 65536 and not parsed.username and not parsed.password
                     and parsed.path in ("", "/") and not parsed.query and not parsed.fragment)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Endpoint fixture phải là origin HTTP loopback có port tường minh.")
    origins = environment.get("FRONTEND_ORIGINS", "http://localhost:3000")
    if not set(origins.split(",")) <= {"http://localhost:3000", "http://127.0.0.1:3000"}:
        raise ValueError("CORS gate chỉ nhận frontend origins local đã duyệt.")
    return {**{key: environment[key] for key in keys}, "FRONTEND_ORIGINS": origins,
            "SEAWEEDFS_INTEGRATION": "1", "SEAWEEDFS_ALLOW_TEST_WRITES": "1"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", nargs="*")
    parser.add_argument("--live-storage", action="store_true", help="Dùng cấu hình runtime đã được duyệt cho gate provider; bị chặn trong CI.")
    parser.add_argument("--confirm-live-storage", metavar="TEST_SCOPE", help="Xác nhận phạm vi fixture live đã được duyệt; chỉ chạy labels tường minh.")
    args = parser.parse_args(argv)
    if args.live_storage and (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")):
        parser.error("CI mặc định không được kết nối storage hoặc cấu hình runtime thật.")
    if args.live_storage and os.environ.get("SEAWEEDFS_INTEGRATION") != "1":
        parser.error("Gate provider cần SEAWEEDFS_INTEGRATION=1 và phạm vi fixture đã được duyệt.")
    if args.live_storage and (not (args.confirm_live_storage or "").strip() or not args.labels):
        parser.error("Live storage cần --confirm-live-storage TEST_SCOPE và test labels tường minh.")
    if args.confirm_live_storage and not args.live_storage:
        parser.error("Xác nhận live chỉ hợp lệ cùng --live-storage.")
    live_environment = None
    if args.live_storage:
        try:
            args.labels = approved_live_labels(args.labels)
            live_environment = approved_live_environment(os.environ, args.confirm_live_storage)
        except ValueError as error:
            parser.error(str(error))

    backend = Path(__file__).resolve().parents[2] / "backend"
    sys.path.insert(0, str(backend))
    os.chdir(backend)
    os.environ["DJANGO_SETTINGS_MODULE"] = "securedrive.test_settings"
    from securedrive.test_environment import approved_database, validate_target
    database = approved_database(os.environ)
    if args.live_storage:
        # Cùng isolation như default trước app.ready(); chỉ cấp lại các biến provider đã duyệt.
        from securedrive import test_settings
        os.environ.update(live_environment)

    import django
    django.setup()
    from django.db import connections
    from django.test.runner import DiscoverRunner
    test_name = "test_bluedrive_" + uuid.uuid4().hex[:16]

    class NonEmptyRunner(DiscoverRunner):
        def build_suite(self, *args, **kwargs):
            suite = super().build_suite(*args, **kwargs)
            if not suite.countTestCases():
                raise RuntimeError("Không tìm thấy test; không được coi 0 bài là PASS.")
            return suite

        def setup_databases(self, **kwargs):
            validate_target(connections["default"], database, test_name)
            return super().setup_databases(**kwargs)

        def teardown_databases(self, old_config, **kwargs):
            # Provider TestCase thuần có thể không yêu cầu DB; chỉ kiểm UUID khi Django đã tạo DB.
            validate_target(connections["default"], database, test_name, testing=bool(old_config))
            return super().teardown_databases(old_config, **kwargs)

    connection = connections["default"]
    connection.settings_dict["TEST"]["NAME"] = test_name
    validate_target(connection, database, test_name)
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [test_name])
        if cursor.fetchone():
            raise SystemExit("Test database đã tồn tại; dừng, không ghi đè.")
    connection.close()
    print(f"Isolated test database: {test_name}", flush=True)
    return bool(NonEmptyRunner(interactive=False).run_tests(args.labels or DEFAULT_LABELS))


if __name__ == "__main__":
    sys.exit(main())
