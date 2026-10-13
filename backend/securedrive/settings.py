import os
from pathlib import Path
from urllib.parse import urlsplit

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


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
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

CORS_ALLOWED_ORIGINS = _env_list("CORS_ALLOWED_ORIGINS") or [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ["Content-Disposition"]
CSRF_TRUSTED_ORIGINS = _env_list("CSRF_TRUSTED_ORIGINS") or [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

NEXTJS_FRONTEND_URL = os.getenv(
    "NEXTJS_FRONTEND_URL",
    "http://127.0.0.1:3000" if DEBUG else "",
).rstrip("/")
if NEXTJS_FRONTEND_URL:
    frontend_url = urlsplit(NEXTJS_FRONTEND_URL)
    if (
        frontend_url.scheme not in {"http", "https"}
        or not frontend_url.netloc
        or frontend_url.path
        or frontend_url.query
        or frontend_url.fragment
        or frontend_url.username
        or frontend_url.password
    ):
        raise RuntimeError("NEXTJS_FRONTEND_URL must be an HTTP(S) origin.")
    if not DEBUG and frontend_url.scheme != "https":
        raise RuntimeError("NEXTJS_FRONTEND_URL must use HTTPS when DEBUG is false.")


ROOT_URLCONF = "securedrive.urls"

WSGI_APPLICATION = "securedrive.wsgi.application"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# --- Database ---

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "securedrive"),
        "USER": os.getenv("DB_USER", "securedrive_app"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "5432"),
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

# S3-compatible adapter is opt-in. Existing FileField workflows remain on MEDIA_ROOT
# until the ADR's multipart/session/finalization flow is integrated separately.
SECUREDRIVE_STORAGE_ENDPOINT_URL = os.getenv("SECUREDRIVE_STORAGE_ENDPOINT_URL", "").strip()
SECUREDRIVE_STORAGE_BUCKET = os.getenv("SECUREDRIVE_STORAGE_BUCKET", "").strip()
SECUREDRIVE_STORAGE_REGION = os.getenv("SECUREDRIVE_STORAGE_REGION", "us-east-1").strip()
SECUREDRIVE_STORAGE_ADDRESSING_STYLE = os.getenv(
    "SECUREDRIVE_STORAGE_ADDRESSING_STYLE", "path"
).strip()
SECUREDRIVE_STORAGE_ACCESS_KEY_ID = os.getenv("SECUREDRIVE_STORAGE_ACCESS_KEY_ID", "").strip()
SECUREDRIVE_STORAGE_SECRET_ACCESS_KEY = os.getenv("SECUREDRIVE_STORAGE_SECRET_ACCESS_KEY", "")
SECUREDRIVE_STORAGE_TLS_VERIFY = os.getenv("SECUREDRIVE_STORAGE_TLS_VERIFY", "true").lower() in (
    "true", "1", "yes"
)
SECUREDRIVE_STORAGE_CA_BUNDLE = os.getenv("SECUREDRIVE_STORAGE_CA_BUNDLE", "").strip()
SECUREDRIVE_STORAGE_CONNECT_TIMEOUT = _env_float("SECUREDRIVE_STORAGE_CONNECT_TIMEOUT", 2.0)
SECUREDRIVE_STORAGE_READ_TIMEOUT = _env_float("SECUREDRIVE_STORAGE_READ_TIMEOUT", 10.0)
SECUREDRIVE_STORAGE_MAX_ATTEMPTS = _env_int("SECUREDRIVE_STORAGE_MAX_ATTEMPTS", 3)
SECUREDRIVE_STORAGE_RETRY_BASE_SECONDS = _env_float(
    "SECUREDRIVE_STORAGE_RETRY_BASE_SECONDS", 0.1
)
SECUREDRIVE_STORAGE_RETRY_MAX_SECONDS = _env_float(
    "SECUREDRIVE_STORAGE_RETRY_MAX_SECONDS", 1.0
)
SECUREDRIVE_STORAGE_PRESIGN_MAX_SECONDS = _env_int(
    "SECUREDRIVE_STORAGE_PRESIGN_MAX_SECONDS", 300
)
SECUREDRIVE_STORAGE_SSE = os.getenv("SECUREDRIVE_STORAGE_SSE", "").strip()
SECUREDRIVE_STORAGE_KMS_KEY_ID = os.getenv("SECUREDRIVE_STORAGE_KMS_KEY_ID", "").strip()
SECUREDRIVE_UPLOAD_SCANNER = os.getenv("SECUREDRIVE_UPLOAD_SCANNER", "").strip()
if SECUREDRIVE_STORAGE_ENDPOINT_URL:
    storage_endpoint = urlsplit(SECUREDRIVE_STORAGE_ENDPOINT_URL)
    if storage_endpoint.scheme not in {"http", "https"} or not storage_endpoint.netloc:
        raise RuntimeError("SECUREDRIVE_STORAGE_ENDPOINT_URL must be an HTTP(S) URL.")
    if not DEBUG and storage_endpoint.scheme != "https":
        raise RuntimeError("Object storage must use HTTPS when DEBUG is false.")
    if not DEBUG and not SECUREDRIVE_STORAGE_TLS_VERIFY:
        raise RuntimeError("Object storage TLS certificate verification cannot be disabled.")
    if not DEBUG and SECUREDRIVE_STORAGE_SSE not in {"AES256", "aws:kms"}:
        raise RuntimeError("Server-side encryption must be configured for deployed object storage.")
    if not SECUREDRIVE_STORAGE_BUCKET:
        raise RuntimeError("SECUREDRIVE_STORAGE_BUCKET is required when storage is configured.")

# --- File upload limits (đồng bộ chunk 4 MB ở client) ---
DATA_UPLOAD_MAX_MEMORY_SIZE = 110 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 110 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# --- Security headers (HTTPS đứng trước) ---
SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SECURE_HSTS_SECONDS = _env_int("SECURE_HSTS_SECONDS", 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --- Cookies ---
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = _env_bool("CSRF_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True


def _same_site_cookie(name: str) -> str:
    value = os.getenv(name, "Lax")
    if value not in {"Strict", "Lax", "None"}:
        raise RuntimeError(f"{name} must be Strict, Lax, or None")
    return value


SESSION_COOKIE_SAMESITE = _same_site_cookie("SESSION_COOKIE_SAMESITE")
CSRF_COOKIE_SAMESITE = _same_site_cookie("CSRF_COOKIE_SAMESITE")
if (SESSION_COOKIE_SAMESITE == "None" or CSRF_COOKIE_SAMESITE == "None") and not (
    SESSION_COOKIE_SECURE and CSRF_COOKIE_SECURE
):
    raise RuntimeError("SameSite=None cookies require secure session and CSRF cookies")
if not DEBUG and not (SESSION_COOKIE_SECURE and CSRF_COOKIE_SECURE):
    raise RuntimeError("Secure session and CSRF cookies are required when DEBUG is false")
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
