# BlueDrive (SecureDrive)

BlueDrive is a Django + Next.js file-management SaaS project. It provides personal drives, workspaces, sharing, quota controls, activity/audit records and an administrative console.

> **Project status:** Development/thesis project. Passing automated tests does not by itself establish production security or operational readiness.

## Architecture

| Layer | Current implementation |
| --- | --- |
| Web UI | Next.js 16, React 19, TypeScript and Tailwind CSS 4 (`frontend/`) |
| API, identity, authorization and metadata | Django 5.2 and Django REST Framework (`backend/`) |
| Database | PostgreSQL, accessed with Psycopg 3 |
| Object storage | S3-compatible MinIO AIStor, configured externally |
| File confidentiality | Server-controlled AES-256-GCM encryption for published file content |

For multipart uploads, Django authorizes a session and issues short-lived part URLs, the browser uploads to a **private quarantine** area in MinIO, and a trusted Django finalizer verifies and encrypts the object before publication. Downloads remain Django-mediated for authorization and decryption. Legacy server-mediated uploads and local encrypted media may also exist.

Think of Django as the access-control desk, MinIO as a private warehouse, and the upload finalizer as the inspection/sealing station. Moving boxes directly to the warehouse does **not** bypass access checks or final inspection.

The application uses **server-side application encryption, not end-to-end/zero-knowledge encryption**. The provider controls the keys needed for authorized decryption.

## Repository layout

```text
SecureDrive/
├── .venv/                 # One local Python virtual environment; not tracked
├── backend/               # Django apps, migrations, tests and commands
├── frontend/              # Next.js App Router, components, features and tests
├── docs/                  # Architecture and development documentation
├── .gitignore
└── README.md
```

## Local development (Windows PowerShell)

Prerequisites: Python 3.12, PostgreSQL, a compatible Node.js/npm installation, and access to a configured **private** MinIO service for multipart uploads. The repository does not provision PostgreSQL or MinIO automatically. See [the development guide](docs/DEVELOPMENT.md) for details.

From the repository root:

```powershell
if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    py -3.12 -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt

# Create example-based configuration only if local files do not already exist.
if (-not (Test-Path .\backend\.env)) {
    Copy-Item .\backend\.env.example .\backend\.env
}
if (-not (Test-Path .\frontend\.env.local)) {
    Copy-Item .\frontend\.env.example .\frontend\.env.local
}
```

Edit `backend/.env` with your **own** PostgreSQL credentials, Django secret key, and the existing AES master key for any existing encrypted data. Replace the placeholders in the example; **never regenerate the master key for existing files**. Configure the actual MinIO endpoint, bucket, credentials and required storage policy where multipart upload is used. Keep secrets out of Git and screenshots.

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

The default local URLs are `http://127.0.0.1:8000` for Django and `http://127.0.0.1:3000` for Next.js. Keep frontend API origin, Django CORS/CSRF trusted origins and MinIO browser CORS consistent. MinIO CORS is configured on **MinIO**, not Django.

## Verification

```powershell
# From the repository root: Django checks
.\.venv\Scripts\python.exe .\backend\manage.py check

# From backend/: Django test discovery
cd backend
..\.venv\Scripts\python.exe manage.py test

# From frontend/: type checks, lint and build
cd ..\frontend
npx tsc --noEmit
npm run lint
npm run build
```

Run only **one** Django test suite at a time against the same PostgreSQL test database. Frontend unit-test scripts are listed in [frontend/README.md](frontend/README.md).

## Documentation and safety

- [Developer workflow, configuration and validation](docs/DEVELOPMENT.md)
- [Backend setup and worker operation](backend/README.md)
- [Frontend setup and test scripts](frontend/README.md)
- [Upload/encryption architecture decision](docs/ADR-0001-saas-file-transfer-and-encryption.md)
- [Storage adapter reference](docs/MINIO_STORAGE_ADAPTER.md) — contains **historical** local Docker Compose steps that must be checked against the actual MinIO AIStor deployment before use.
- [API contract document](docs/API_CONTRACT_V1.md) — includes proposed contracts; do not assume every proposal is implemented.

**Do not delete** PostgreSQL databases, `backend/media/`, encrypted `.enc` files, MinIO data/volumes, migrations, or encryption keys as part of source-code cleanup. Do not run destructive Docker volume commands for the existing AIStor deployment.
