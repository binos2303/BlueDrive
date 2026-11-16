# BlueDrive backend

The `backend/` directory contains the Django 5.2 API, server-side authorization, PostgreSQL metadata, quotas, upload finalization, encrypted file services and regression tests. Next.js is the primary UI; some legacy Django views remain for compatibility.

## Runtime and dependencies

- CPython 3.12.10; use the **single repository-root** `.venv/` environment. `infra/bootstrap-python.ps1` creates/repairs it using a project-local, hash-pinned full CPython runtime; it does not change system Python/PATH or recreate site-packages.
- PostgreSQL via `django.db.backends.postgresql` and `psycopg[binary]==3.3.6` (Psycopg 3).
- Dependencies are pinned in `backend/requirements.txt`.
- The object storage adapter uses `boto3` for S3-compatible operations. The agreed target is SeaweedFS-only with independent Platform/Enterprise storage and separate Filer PostgreSQL; see [ADR-0010](../docs/ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md), [P0 baseline](../docs/REFACTOR_P0_BASELINE_2026-11-16.md) and [SeaweedFS runbook](../infra/seaweedfs/README.md). Provider acceptance is separate from source implementation; MinIO cutover is no longer the requested roadmap.

From repository root (PowerShell):

```powershell
.\infra\bootstrap-python.ps1 -InstallDependencies
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe .\backend\manage.py check --settings securedrive.test_settings
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
| `SECUREDRIVE_STORAGE_*` | SeaweedFS S3 connection, private bucket, access, TLS and SSE/KMS policy; preserve existing revision targets |
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

Prepare the [dedicated PostgreSQL service](../docs/DEVELOPMENT.md#41-postgresql-test-riêng) before running these commands. `securedrive.test_settings` keeps an allowlisted process environment, disables dotenv and runtime credential providers, and creates test-only keys/media/email. `BLUEDRIVE_TEST_DB_TARGET` selects the fixed local or CI profile; arbitrary host/port/name/role overrides are rejected. The runner verifies the test service identity/marker before creating or dropping its UUID database. It keeps the authentication/CSRF middleware, password validators, ACL/quota services and PostgreSQL constraints. Runtime `DB_*`, feature flags and `DJANGO_SETTINGS_MODULE` do not select the default runner's database or behavior.

```powershell
# Từ repository root, dùng runner hiện có với PostgreSQL test DB riêng mới.
.\.venv\Scripts\python.exe .\infra\seaweedfs\regression.py
# Có thể thêm Django test label để chỉ chạy phần liên quan.
```

The existing runner chooses a previously absent random PostgreSQL test database and accepts Django test labels. It requires the test role to create a database and rejects zero discovery/keepdb. **Do not launch concurrent suites against the same test DB** or delete another process's test DB to fix an error. Enabled-feature tests use explicit settings plus scoped binding/FakeS3 fixtures; CI runs them separately as well as in the full suite. Live SeaweedFS gates require `--live-storage --confirm-live-storage <approved-fixture-scope> <labels>`, `SEAWEEDFS_INTEGRATION=1` and a dedicated operator-approved `bluedrive-test-<scope>` bucket/identity; CI rejects that mode. Only the two reviewed SeaweedFS provider classes are allowed (module labels normalize to those classes). Live mode keeps isolated test settings, temporary media, locmem email and the approved PostgreSQL target, restoring only allowlisted provider fixture variables. It never loads serving dotenv/settings. Default skipped provider tests do not certify a provider. See [ADR-0011](../docs/ADR-0011-isolated-test-baseline-and-local-fonts.md), [AGENTS.md](../AGENTS.md), [MAP.md](../MAP.md).

## Data and security invariants

- PostgreSQL holds file metadata and encryption metadata; object storage holds private quarantine/published objects. Legacy encrypted content may remain under `backend/media/`.
- The server—not a workspace selector header or client-supplied object key—decides authorization, ownership, quota and publication state.
- Current multipart publication stores verified S3 objects without application AES encryption. Provider SSE is optional and must be configured/verified separately. Legacy encrypted files retain server-controlled AES-256-GCM and require the original master key.
- With `SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED`, authorized eligible S3 files use short-lived, version-pinned GET URLs. Legacy encrypted files, previews and ZIP downloads remain Django-mediated. See the [download implementation](../docs/PRESIGNED_DOWNLOAD_2026-11-07.md); the encryption ADR describes an earlier architecture, not a guarantee for current multipart uploads.
- Do not delete migration files, encrypted media, MinIO objects, or database records during repository cleanup.

See [developer workflow](../docs/DEVELOPMENT.md), [storage adapter guide](../docs/MINIO_STORAGE_ADAPTER.md) and [architecture decision](../docs/ADR-0001-saas-file-transfer-and-encryption.md).

## Storage Control Center S2

The MinIO migration workflow described in [ADR-0008](../docs/ADR-0008-platform-storage-copy-and-publication.md) is historical; `audit_storage_cutover` and `migrate_platform_storage` are absent from the P0 working tree. Do not run that plan or retarget existing locations. The [P0 backlog](../docs/REFACTOR_P0_BASELINE_2026-11-16.md) defines future qualification and retirement gates without a MinIO cutover/data-copy requirement.

Deploy additive `infrastructure.0006_allow_deleted_upload_history` before the updated pinned permanent-delete path. It preserves successful upload/quota history after file removal. Do not reverse it once detached successful history exists; use a reviewed forward fix. Implementation/testing does not apply this migration to the serving database.

Connect Existing and immutable upload/location targets are implemented behind default-OFF flags. Configure approved server-side profiles, never browser-supplied endpoint/credentials. Read checks do not activate routing; temporary-bucket probes are LAB-only and independently gated. Existing global storage remains the fallback for legacy records only. See [S2 operator runbook](../docs/STORAGE_CONTROL_CENTER_S2_RUNBOOK.md) and [connection/pinning ADR](../docs/ADR-0003-immutable-storage-connections.md) before enabling anything. Restart all web/finalizer processes to the same version before any routing rollout. No existing process was automatically restarted during implementation.

S3 adds the separately default-OFF `SECUREDRIVE_STORAGE_TOPOLOGY_ENABLED` flag and a position-only layout preference endpoint. It reuses the S1 schema, does not call storage, and does not enable node/pool operations. Personal layouts require view access; shared defaults require configure. See [ADR-0004](../docs/ADR-0004-topology-layout-preferences.md). Real SeaweedFS acceptance remains separate; adding a canvas does not certify provider health.

S4 adds additive migration `infrastructure.0005_telemetry_snapshots_and_alerts`, the default-OFF `SECUREDRIVE_STORAGE_MONITORING_ENABLED` flag, approved server-side `SECUREDRIVE_STORAGE_MONITORING_PROFILES`, snapshot/incident APIs and an explicitly launched read-only `collect_storage_telemetry` command. It never starts a collector with the web server. SSE requires an approved ASGI deployment; ordinary WSGI uses30s polling. Monitor permission is separate from inventory/configure. Read [ADR-0005](../docs/ADR-0005-scoped-storage-monitoring.md) and the [S4 runbook](../docs/STORAGE_CONTROL_CENTER_S4_RUNBOOK.md) before configuring profiles or starting collection. Code tests do not close real-provider G2/G4 gates.
