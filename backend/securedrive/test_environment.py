"""Contract cố định cho process test và PostgreSQL thử nghiệm đã được duyệt."""
import os
import re

from django.core.exceptions import ImproperlyConfigured


CONTROL_DATABASE = "bluedrive_test_control"
TEST_ROLE = "bluedrive_test"
TARGET_MARKER = "BlueDrive isolated regression control v1"
PROFILES = {"local": "55432", "ci": "5432"}
OS_VARIABLES = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG", "LC_ALL", "TZ", "CI", "GITHUB_ACTIONS", "PYTHONUNBUFFERED"}


class RunnerRequired:
    def __init__(self, **kwargs):
        raise ImproperlyConfigured("Dùng infra/seaweedfs/regression.py để giữ guard tạo/hủy PostgreSQL test DB.")


def approved_database(environment):
    profile = environment.get("BLUEDRIVE_TEST_DB_TARGET", "local")
    if profile not in PROFILES:
        raise ImproperlyConfigured("PostgreSQL test target chưa được duyệt.")
    expected = {"NAME": CONTROL_DATABASE, "HOST": "127.0.0.1", "PORT": PROFILES[profile], "USER": TEST_ROLE}
    for key, value in expected.items():
        if environment.get("BLUEDRIVE_TEST_DB_" + key, value) != value:
            raise ImproperlyConfigured("PostgreSQL test name/host/port/role không khớp profile đã duyệt.")
    return {**expected, "PASSWORD": environment.get("BLUEDRIVE_TEST_DB_PASSWORD", "")}


def isolated_environment(environment):
    """Không trả environment runtime về sau import; fixture có thể cấp biến trong scope riêng."""
    database = approved_database(environment)
    result = {key: value for key, value in environment.items() if key.upper() in OS_VARIABLES}
    result.update({"BLUEDRIVE_TEST_DB_" + key: value for key, value in database.items()})
    result["BLUEDRIVE_TEST_DB_TARGET"] = environment.get("BLUEDRIVE_TEST_DB_TARGET", "local")
    result.update({
        "DJANGO_SETTINGS_MODULE": "securedrive.test_settings",
        "PYTHON_DOTENV_DISABLED": "1",
        "SEAWEEDFS_INTEGRATION": "0",
        "SECUREDRIVE_MINIO_INTEGRATION": "false",
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        "AWS_CONFIG_FILE": os.devnull,
        "BOTO_CONFIG": os.devnull,
        "AWS_EC2_METADATA_DISABLED": "true",
        "PGPASSFILE": os.devnull,
    })
    return result


def validate_target(connection, database, test_name, *, testing=False):
    """Kiểm đích bất biến trước cả tạo và hủy; không suy an toàn từ prefix DB."""
    actual = connection.settings_dict
    if not re.fullmatch(r"test_bluedrive_[0-9a-f]{16}", test_name):
        raise ImproperlyConfigured("Tên test database không thuộc lifecycle UUID của runner.")
    expected_name = test_name if testing else CONTROL_DATABASE
    if (actual["NAME"] != expected_name or actual["TEST"]["NAME"] != test_name
            or any(str(actual[key]) != database[key] for key in ("HOST", "PORT", "USER", "PASSWORD"))
            or actual["ENGINE"] != "django.db.backends.postgresql"
            or actual.get("OPTIONS") != {"hostaddr": "127.0.0.1", "passfile": os.devnull}):
        raise ImproperlyConfigured("PostgreSQL test connection đã lệch khỏi target được duyệt.")
    import psycopg
    with psycopg.connect(dbname=CONTROL_DATABASE, host=database["HOST"], hostaddr="127.0.0.1",
                          port=database["PORT"], user=database["USER"], password=database["PASSWORD"],
                          passfile=os.devnull, connect_timeout=5) as control:
        row = control.execute(
            "SELECT current_database(), current_user, inet_server_port(), "
            "shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = current_database()"
        ).fetchone()
        if row != (CONTROL_DATABASE, TEST_ROLE, 5432, TARGET_MARKER):
            raise ImproperlyConfigured("PostgreSQL không có identity/marker của test service đã duyệt.")
