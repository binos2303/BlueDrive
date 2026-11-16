# BlueDrive (SecureDrive)

Kiến trúc đích đã thống nhất: **SeaweedFS-only**, storage Platform/Enterprise độc lập, PostgreSQL Filer riêng, Enterprise My Drive thuộc Organization và client-side encryption có organization recovery. Xem [ADR-0010](docs/ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md) và [baseline/backlog P0 ngày 16/11/2026](docs/REFACTOR_P0_BASELINE_2026-11-16.md). P0 chỉ đồng bộ tài liệu/kiểm thử, chưa triển khai các gap Enterprise/CSE. Không thực hiện cutover hoặc xóa dữ liệu runtime; lộ trình MinIO cũ là lịch sử.

BlueDrive is a Django + Next.js file-management SaaS project. It provides personal drives, workspaces, sharing, quota controls, activity/audit records and an administrative console.

> **Project status:** Development/thesis project. Passing automated tests does not by itself establish production security or operational readiness.

## Project context

Before each development task, read [AGENTS.md](AGENTS.md), the relevant sections of [MAP.md](MAP.md), and any instructions in the affected subdirectory. The map links source modules, tests, runbooks and existing architecture decisions. Long-lived decisions continue in `docs/ADR-*`; see [ADR-0006](docs/ADR-0006-project-context-and-development-guidance.md). The [Task 01 handoff](docs/BLUEDRIVE_BAN_GIAO_TASK01.md) remains dated historical evidence; the current target and implementation gaps are in P0 above.

## Architecture

| Layer | Current implementation |
| --- | --- |
| Web UI | Next.js 16, React 19, TypeScript and Tailwind CSS 4 (`frontend/`) |
| API, identity, authorization and metadata | Django 5.2 and Django REST Framework (`backend/`) |
| Database | PostgreSQL, accessed with Psycopg 3 |
| Object storage | Shared S3 adapter, immutable connection revisions and Platform/Enterprise bindings; target is SeaweedFS-only, physical provider acceptance remains a separate gate |
| File confidentiality | Private S3 objects, optional storage-provider SSE; AES-256-GCM for legacy encrypted files |

For multipart uploads, Django authorizes a session and issues short-lived part URLs. The browser uploads to a **private staging** area in object storage, and a trusted finalizer verifies size/checksum and publishes the object. Current multipart publication does not apply application AES encryption; configure and verify provider SSE separately when encryption at rest is required. When `SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED` is enabled, eligible S3 files download through short-lived, version-pinned GET URLs after Django authorization. Encrypted legacy files, previews and ZIP downloads remain Django-mediated. See [the download implementation and local validation](docs/PRESIGNED_DOWNLOAD_2026-11-07.md).

Think of Django as the access-control desk, object storage as a private warehouse, and the upload finalizer as the inspection/sealing station. Moving boxes directly to the warehouse does **not** bypass access checks or final inspection.

The application does **not currently** provide client-side/end-to-end encryption. Legacy application encryption uses server-controlled keys. Client-side AES-256-GCM with public/private keys and organization recovery is the agreed target; its detailed key/format/recovery contract needs review before implementation. Enterprise employees' My Drive must belong to their Organization; current personal-first provisioning/context remains a documented gap. A private bucket alone does not prove encryption at rest, and an unconfigured scanner does not provide malware scanning.

## Repository layout

```text
SecureDrive/
├── .venv/                 # One local Python virtual environment; not tracked
├── backend/               # Django apps, migrations, tests and commands
├── frontend/              # Next.js App Router, components, features and tests
├── docs/                  # Architecture and development documentation
├── infra/seaweedfs/        # Compose, storage gates and isolated test runner
├── AGENTS.md              # Main development and safety instructions
├── MAP.md                 # Source and documentation map
├── .gitignore
└── README.md
```

## Local development (Windows PowerShell)

Prerequisites: Python 3.12, application PostgreSQL, compatible Node.js/npm and configured **private** SeaweedFS S3 storage. The [Platform Compose](infra/seaweedfs/README.md) and [Enterprise Lab](infra/enterprise-lab/README.md) keep Filer PostgreSQL separate from the application DB and from each other. Existing pinned data keeps its original connection; changing the target architecture does not authorize retargeting or deleting it. See [the development guide](docs/DEVELOPMENT.md).

From the repository root:

```powershell
.\infra\bootstrap-python.ps1 -InstallDependencies

# Create example-based configuration only if local files do not already exist.
if (-not (Test-Path .\backend\.env)) {
    Copy-Item .\backend\.env.example .\backend\.env
}
if (-not (Test-Path .\frontend\.env.local)) {
    Copy-Item .\frontend\.env.example .\frontend\.env.local
}
```

Edit `backend/.env` with your **own** PostgreSQL credentials, Django secret key, and the existing AES master key for any existing encrypted data. Replace the placeholders in the example; **never regenerate the master key for existing files**. For a new environment, configure SeaweedFS using the approved profile/binding and required private-bucket policy. Do not overwrite an existing endpoint or credential to redirect pinned data. Keep secrets out of Git and screenshots.

After provisioning PostgreSQL and editing configuration:

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py migrate
.\.venv\Scripts\python.exe .\backend\manage.py check
```

Run the development processes in separate terminals:

```powershell
# Terminal A — API
.\.venv\Scripts\python.exe .\backend\manage.py runserver

# Terminal B — UI
cd frontend
npm install
npm run dev

# Terminal C — multipart finalizer; run from repository root
.\.venv\Scripts\python.exe .\backend\manage.py run_upload_finalizer
```

The default local URLs are `http://127.0.0.1:8000` for Django and `http://127.0.0.1:3000` for Next.js. Keep frontend API origin, Django CORS/CSRF trusted origins and SeaweedFS browser CORS consistent. Object-storage CORS is configured on the storage service separately from Django.

## Verification

Prepare the dedicated PostgreSQL test service and `BLUEDRIVE_TEST_DB_*` variables using [the test setup](docs/DEVELOPMENT.md#41-postgresql-test-riêng). Tests use isolated settings; they do not borrow the serving `.env`, storage credentials or media directory. Poppins is included locally with its license, so the production build does not fetch Google Fonts. See [ADR-0011](docs/ADR-0011-isolated-test-baseline-and-local-fonts.md).

```powershell
# From the repository root: Django checks
.\.venv\Scripts\python.exe .\backend\manage.py check --settings securedrive.test_settings

# Từ repository root: dùng PostgreSQL test database riêng
.\.venv\Scripts\python.exe .\infra\seaweedfs\regression.py

# From frontend/: type checks, lint and build
cd frontend
npx --no-install next typegen
npx --no-install tsc --noEmit
npm run lint
npm run build
```

Run only **one** Django test suite at a time against the same PostgreSQL test database. Frontend unit-test scripts are listed in [frontend/README.md](frontend/README.md).

## Documentation and safety

- [Developer workflow, configuration and validation](docs/DEVELOPMENT.md)
- [Backend setup and worker operation](backend/README.md)
- [Frontend setup and test scripts](frontend/README.md)
- [Current architecture decision](docs/ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md), [P0 inventory and P1–P8 gates](docs/REFACTOR_P0_BASELINE_2026-11-16.md)
- [Earlier upload/encryption decision](docs/ADR-0001-saas-file-transfer-and-encryption.md), [historical MinIO adapter reference](docs/MINIO_STORAGE_ADAPTER.md) — historical setup is not the current deployment procedure.
- [API contract document](docs/API_CONTRACT_V1.md) — includes proposed contracts; do not assume every proposal is implemented.

**Do not delete** application/Filer databases, `backend/media/`, encrypted `.enc` files, current object data/volumes, migrations or encryption keys as part of source-code cleanup. Removing MinIO from the target architecture does not authorize changing current runtime data or running destructive Docker volume commands.
