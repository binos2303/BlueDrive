"""Cấu hình test không đọc .env hoặc kế thừa cấu hình ứng dụng đang phục vụ."""
import base64
import os
import secrets
import sys
import tempfile
from .test_environment import approved_database, isolated_environment
from django.core.exceptions import ImproperlyConfigured


if "securedrive.settings" in sys.modules:
    raise ImproperlyConfigured("Test settings cần process mới, chưa import runtime settings.")
_database = approved_database(os.environ)
_process_environment = isolated_environment(os.environ)

_environment = {
    "PYTHON_DOTENV_DISABLED": "1",
    "SECRET_KEY": secrets.token_urlsafe(48),
    "DEBUG": "true",
    "ALLOWED_HOSTS": "testserver,localhost,127.0.0.1",
    **{"DB_" + key: value for key, value in _database.items()},
    "SECUREDRIVE_AES_KEY": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
    "SECUREDRIVE_STORAGE_ENDPOINT_URL": "https://storage.example.invalid",
    "SECUREDRIVE_STORAGE_BUCKET": "bluedrive-test",
    "SECUREDRIVE_STORAGE_ACCESS_KEY_ID": secrets.token_hex(12),
    "SECUREDRIVE_STORAGE_SECRET_ACCESS_KEY": secrets.token_hex(24),
    "SECUREDRIVE_PLATFORM_SEAWEEDFS_MASTER_URL": "http://127.0.0.1:9",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "DEFAULT_FROM_EMAIL": "test@example.invalid",
}

# Giữ allowlist suốt process vì service có thể đọc credential sau lúc import settings.
os.environ.clear()
os.environ.update(_process_environment)
os.environ.update(_environment)
from .settings import *
DATABASES["default"]["OPTIONS"] = {"hostaddr": "127.0.0.1", "passfile": os.devnull}
# Chặn manage.py test đi vòng UUID/marker guards của entry point đã được duyệt.
TEST_RUNNER = "securedrive.test_environment.RunnerRequired"
# Chỉ giữ key AES mà reader legacy cần; cấu hình Django còn lại nằm trong settings.
os.environ.clear()
os.environ.update(_process_environment)

# Reader AES legacy đọc key trực tiếp từ process env; chỉ cấp key test ngẫu nhiên, không dùng key runtime.
os.environ["SECUREDRIVE_AES_KEY"] = SECUREDRIVE_AES_KEY
# Các suite provider chỉ được opt-in qua runner --live-storage, không từ shell kế thừa.
os.environ["SEAWEEDFS_INTEGRATION"] = "0"
os.environ["SECUREDRIVE_MINIO_INTEGRATION"] = "false"
_media_directory = tempfile.TemporaryDirectory(prefix="bluedrive-tests-media-")
MEDIA_ROOT = _media_directory.name
