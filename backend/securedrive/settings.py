"""Django settings cho securedrive.

Triết lý bảo mật:
- Không hard-code secret. Mọi secret qua .env → os.getenv().
- Secure-by-default headers (triển khai dưới HTTPS).
- Crypto env-vars được khai báo tập trung để crypto modules đọc.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env trước khi chạy. Production inject thẳng qua môi trường runtime.
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("true", "1", "yes")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_list(name: str) -> list[str]:
    raw = os.getenv(name, "").strip()
    return [v.strip() for v in raw.split(",") if v.strip()]


# --- Core ---
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is required (set in .env)")

DEBUG = _env_bool("DEBUG", False)
ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS") or ["localhost", "127.0.0.1"]

# --- Apps & middleware ---
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",

    "corsheaders",
    "rest_framework",

    "accounts",
    "folders",
    "files",
    "security",
    "logs",
    "sharing",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
]


ROOT_URLCONF = "securedrive.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "securedrive.wsgi.application"

# --- Database ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("DB_NAME", "securedrive"),
        "USER": os.getenv("DB_USER", "securedrive_user"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": (
                "SET sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION',"
                "innodb_strict_mode=1"
            ),
        },
    }
}

# --- Auth password validators ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n (niên luận tiếng Việt) ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True

# --- Static / Media ---
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- File upload limits (đồng bộ chunk 4 MB ở client) ---
DATA_UPLOAD_MAX_MEMORY_SIZE = 110 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 110 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# --- Security headers (HTTPS đứng trước) ---
SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = _env_int("SECURE_HSTS_SECONDS", 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --- Cookies ---
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = _env_bool("CSRF_COOKIE_SECURE", False)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# --- Crypto env-vars ---
SECUREDRIVE_AES_KEY = os.getenv("SECUREDRIVE_AES_KEY", "")
SECUREDRIVE_PEPPER = os.getenv("SECUREDRIVE_PEPPER", "")
SECUREDRIVE_CURRENT_KEY_ID = _env_int("SECUREDRIVE_CURRENT_KEY_ID", 1)

# --- Logging ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "loggers": {
        "security": {"handlers": ["console"], "level": "INFO"},
        "sharing": {"handlers": ["console"], "level": "INFO"},
        "files": {"handlers": ["console"], "level": "INFO"},
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
