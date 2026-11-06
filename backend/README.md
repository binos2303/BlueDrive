# BlueDrive backend

The `backend/` directory contains the Django 5.2 API, server-side authorization, PostgreSQL metadata, quotas, upload finalization, encrypted file services and regression tests. Next.js is the primary UI; some legacy Django views remain for compatibility.

## Runtime and dependencies

- Python 3.12; use the **single repository-root** `.venv/` environment on the Windows development machine.
- PostgreSQL via `django.db.backends.postgresql` and `psycopg[binary]==3.3.6` (Psycopg 3).
- Dependencies are pinned in `backend/requirements.txt`.
- The object storage adapter uses `boto3` for S3-compatible MinIO operations.

From repository root (PowerShell):

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe .\backend\manage.py check
```

Do **not** recreate `backend/venv` or reinstall `psycopg2-binary`; Phase 1 consolidated the environment and driver.

## Configuration

Django loads `backend/.env` (if present) from `backend/securedrive/settings.py`. Create it from `backend/.env.example` **only if no existing `.env` is present**; fill in the placeholders yourself. Environment variables can also be supplied by the deployment runtime.

| Setting(s) | Purpose |
| --- | --- |
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` | Django runtime and host policy |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection |
| `NEXTJS_FRONTEND_URL` | Origin used for frontend redirects |
| `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` | Allowed/trusted browser origins |
| `SECUREDRIVE_AES_KEY` | Base64-encoded **32-byte** server master key; needed for encrypted file operations |
| `SECUREDRIVE_STORAGE_*` | MinIO/S3 endpoint, private bucket, access, TLS and optional SSE/KMS policy |
| `SECUREDRIVE_UPLOAD_SCANNER` | Optional trusted scanner callable; empty does **not** mean objects are malware-scanned |

Generate **new development-only** keys using Django's `get_random_secret_key()` for `SECRET_KEY` and a 32-byte random value for `SECUREDRIVE_AES_KEY`. Example for a **new empty environment only**:

```powershell
.\.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
.\.venv\Scripts\python.exe -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
```

**Existing encrypted data depends on the original master key. Do not rotate it by replacing the environment value without an approved key-migration procedure.** Keep all keys, database credentials and access tokens outside version control.

For local `DEBUG=true`, Django defaults to HTTP-friendly cookie flags; production settings require HTTPS, secure cookies, appropriate CORS/CSRF origins, and storage encryption/TLS policy. Do not carry development settings into production.

## Commands

From `backend/` with the root virtual environment active (or using `..\.venv\Scripts\python.exe` explicitly):

```powershell
python manage.py migrate
python manage.py check
python manage.py runserver
```

For **direct multipart uploads** the application uses a persistent upload session and finalization jobs. Start a **separate** local worker when that flow is enabled:

```powershell
python manage.py run_upload_finalizer
```

`python manage.py finalize_uploads` performs one finalization sweep; `python manage.py cleanup_uploads` cleans expired upload sessions and reservations. These commands act on configured real storage/DB state; arrange periodic execution and monitoring deliberately rather than treating them as harmless test commands.

## Tests

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py test
```

The Django test runner uses a PostgreSQL test database (for example, `test_securedrive`). **Do not launch concurrent full test suites** against the same test DB. If it already exists, determine which process owns the connection before answering a prompt to delete it. Optional MinIO integration tests may be skipped unless explicitly enabled/configured.

## Data and security invariants

- PostgreSQL holds file metadata and encryption metadata; object storage holds private quarantine/published objects. Legacy encrypted content may remain under `backend/media/`.
- The server—not a workspace selector header or client-supplied object key—decides authorization, ownership, quota and publication state.
- Published objects use server-controlled AES-256-GCM (not end-to-end encryption). Download remains Django-mediated.
- Do not delete migration files, encrypted media, MinIO objects, or database records during repository cleanup.

See [developer workflow](../docs/DEVELOPMENT.md), [storage adapter guide](../docs/MINIO_STORAGE_ADAPTER.md) and [architecture decision](../docs/ADR-0001-saas-file-transfer-and-encryption.md).
