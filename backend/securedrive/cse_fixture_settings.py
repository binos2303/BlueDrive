"""Entry point cô lập cho CSE, chỉ chấp nhận DB fixture đã đánh dấu."""
import json
import os
from pathlib import Path
import sys

import psycopg
from django.core.exceptions import ImproperlyConfigured
from .test_environment import isolated_environment

if "securedrive.settings" in sys.modules:
    raise ImproperlyConfigured("CSE fixture needs a fresh process.")

_path = Path(os.environ["BLUEDRIVE_CSE_FIXTURE_CONFIG"]).resolve(strict=True)
_config = json.loads(_path.read_text(encoding="utf-8"))
_name = "bluedrive_p6_fixture_application"
_port = 55439
_endpoint = "http://127.0.0.1:18339"
_public_endpoint = "http://s3.localhost:18339"
_bucket = "bluedrive-test-p6-cse"
with psycopg.connect(host="127.0.0.1", hostaddr="127.0.0.1", port=_port, dbname=_name,
                     user=_name, password=_config["database_material"], passfile=os.devnull,
                     connect_timeout=3) as _connection:
    _identity = _connection.execute(
        "SELECT current_database(), current_user, shobj_description(oid, 'pg_database') "
        "FROM pg_database WHERE datname = current_database()"
    ).fetchone()
if _identity != (_name, _name, "BlueDrive P6 CSE isolated application fixture v1"):
    raise ImproperlyConfigured("CSE fixture database marker mismatch.")

_environment = isolated_environment(os.environ)
os.environ.clear()
os.environ.update(_environment)
os.environ.update({
    "PYTHON_DOTENV_DISABLED": "1",
    "SECRET_KEY": _config["django_material"],
    "SECUREDRIVE_AES_KEY": _config["aes_material"],
    "DEBUG": "true",
    "ALLOWED_HOSTS": "localhost,127.0.0.1",
    "DB_NAME": _name,
    "DB_USER": _name,
    "DB_PASSWORD": _config["database_material"],
    "DB_HOST": "127.0.0.1",
    "DB_PORT": str(_port),
    "NEXTJS_FRONTEND_URL": "http://127.0.0.1:13600",
    "CORS_ALLOWED_ORIGINS": "http://127.0.0.1:13600",
    "CSRF_TRUSTED_ORIGINS": "http://127.0.0.1:13600",
    "SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED": "true",
    "SECUREDRIVE_STORAGE_RUNTIME_PROBES_ENABLED": "true",
    "SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED": "true",
    "SECUREDRIVE_STORAGE_CONNECTION_PROFILES": json.dumps(_config["profiles"]),
    "BLUEDRIVE_CSE_STORAGE_ID": _config["storage_identity"],
    "BLUEDRIVE_CSE_STORAGE_MATERIAL": _config["storage_material"],
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
})

from .settings import *

DATABASES["default"]["OPTIONS"] = {"hostaddr": "127.0.0.1", "passfile": os.devnull}
MEDIA_ROOT = _path.parent / "media"
CSE_FIXTURE = {
    "writer": _config.get("writer") is True,
    "required": _config.get("required") is True,
    "allow_unscanned": _config.get("allow_unscanned") is True,
    "tenant": _config.get("tenant"),
    "workspace": _config.get("workspace"),
    "pin": _config.get("pin"),
    "directory": str(_path.parent / "signed-directory.json"),
    "endpoint": _endpoint,
    "public_endpoint": _public_endpoint,
    "bucket": _bucket,
}
