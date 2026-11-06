# BlueDrive development workflow

**Scope:** development and validation of the current Django + Next.js repository. This document is not a production runbook or a backup/restore procedure.

## 1. Source-of-truth and local state

The repository contains application source, database migrations and scripts; **local runtime data is not disposable source code**. PostgreSQL user/file metadata, `backend/media/` encrypted files, MinIO AIStor objects/bind mounts/volumes, and encryption keys must be backed up and maintained as a consistent set. A Git commit or Django migration does not back up stored user files.

The only project Python environment is the **repository-root `.venv/`**. Do not create or select `backend/venv` in VS Code. `.vscode/settings.json` may point to `${workspaceFolder}/.venv/Scripts/python.exe`.

Example Windows PowerShell session, from repository root:

```powershell
cd C:\Users\dang2\Project\SecureDrive
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe .\backend\manage.py check
```

The path above matches the current workstation; adapt it on other machines.

## 2. Local environment configuration

- Django reads `backend/.env`; Next.js reads `frontend/.env.local`.
- Both are ignored by Git. Example files are committed solely as templates with **empty placeholders** or non-secret local origins.
- The Django API typically runs at `http://127.0.0.1:8000`; Next.js at `http://127.0.0.1:3000`.
- Set `NEXT_PUBLIC_API_BASE_URL` to the Django origin, not the MinIO endpoint.
- Keep `NEXTJS_FRONTEND_URL`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` aligned with the actual browser origin.
- Enable MinIO multipart upload only when the private bucket, endpoint, credentials, TLS policy and browser CORS are correctly configured.
- Keep the existing `SECUREDRIVE_AES_KEY` for any existing encrypted files. Replacing it without rewrapping keys can make them unreadable.

**Storage caution:** The older `docs/MINIO_STORAGE_ADAPTER.md` describes a local Docker Compose scenario and references files absent from the reviewed tracked snapshot. The actual MinIO AIStor deployment is managed separately. **Never run `docker compose down -v`, delete volumes, or remove a bind mount as a cleanup step.** Validate every storage instruction against the real deployment before use.

## 3. Start the application

Run these from separate PowerShell terminals. Use the repository-root `.venv` for Django and local npm for Next.js.

```powershell
# Django API, from repository root
.\.venv\Scripts\python.exe .\backend\manage.py runserver
```

```powershell
# Next.js
cd frontend
npm run dev
```

```powershell
# Trusted upload finalization worker, from repository root
.\.venv\Scripts\python.exe .\backend\manage.py run_upload_finalizer
```

The worker is required to publish completed multipart uploads in local development. In deployment the equivalent job must be supervised and monitored. `cleanup_uploads` is a state-changing maintenance command: schedule it under a deliberate operations policy, not as a casual diagnostic command.

## 4. Verify changes

For **documentation-only** changes:

```powershell
git status --short
git --no-pager diff --check
git --no-pager diff --stat
```

For **code or dependency** changes, run the relevant suites; for full regression:

```powershell
# Backend: from the backend directory
cd backend
..\.venv\Scripts\python.exe manage.py check
..\.venv\Scripts\python.exe manage.py test

# Frontend
cd ..\frontend
npx tsc --noEmit
npm run lint
npm run build
```

Run feature unit-test scripts defined in `frontend/package.json` as appropriate. Django's full suite was 349 tests with 9 skipped at the Phase 2.1 checkpoint; these numbers can change as tests evolve.

**PostgreSQL test database:** Running two Django test suites at the same time can leave a session connected to the same `test_*` database and prevent teardown/recreation. Only run one full test suite per test database at a time. Do not terminate another legitimate test's DB session or delete the application's real database.

## 5. Git and cleanup discipline

1. Check `git status --short` and start from a clean working tree.
2. Review a narrow change set. Do not mix documentation and security/behavior refactoring in one commit.
3. Back up any replaced files to **Windows Downloads** before applying automated cleanup scripts. Never store clean-up exports inside the repository.
4. Avoid broad deletions. In particular, **never delete** migrations, `.enc` media, PostgreSQL data, MinIO objects/volumes, or cryptographic keys based on static import results.
5. Run checks; use `git --no-pager diff --check` and `git --no-pager diff --cached --stat` to avoid the interactive `less` pager.
6. Commit only inspected, related paths; do not use `git add .` when unreviewed files exist.

Historical Phase 2.1 cleanup removed 17 hash-verified unused files in commit `f932b95` after 349 Django tests and frontend checks passed. The change was backed up separately in Downloads.

## 6. Documentation update policy

- Root `README.md`: project overview and validated quick start.
- `backend/README.md`: backend setup, configuration, workers and tests.
- `frontend/README.md`: frontend setup, environment, test scripts and API boundary.
- `docs/`: architecture decisions, proposed API contracts, implementation-specific guides, and this workflow.
- Where older documents describe proposals or past baselines, label them **historical/proposed** rather than implying the feature is currently deployed.

All nontrivial refactors must preserve tests and authorization invariants. A front-end component with no static import may still be an App Router page, dynamically imported component, or server-discovered module; inspect runtime references before removal.
