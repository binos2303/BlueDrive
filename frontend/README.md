# BlueDrive frontend

This directory is the **Next.js 16 App Router** frontend for personal drives, workspaces, account settings and the platform administration console. It uses React 19, TypeScript and Tailwind CSS 4.

Kiến trúc đích: [ADR-0010](../docs/ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md). Enterprise My Drive thuộc Organization; CSE AES-256-GCM/public-private key/organization recovery là thiết kế đích, **chưa được triển khai** trong upload client hiện tại. Xem [P0 inventory và gates P1–P8](../docs/REFACTOR_P0_BASELINE_2026-11-16.md) trước thay context, upload hoặc UI.

## Development

Use a Node.js release compatible with Next.js 16 and the repository's Node test commands (`--experimental-strip-types`). Check your Node/npm versions with `node --version` and `npm --version`.

```powershell
cd frontend
npm install
```

Create `frontend/.env.local` from `frontend/.env.example` **only if `.env.local` does not already exist**:

```powershell
if (-not (Test-Path .\.env.local)) {
    Copy-Item .\.env.example .\.env.local
}
```

Required application configuration:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

This public environment variable identifies the Django API origin. It is compiled into browser code, so **never put credentials, API secrets or storage keys in any `NEXT_PUBLIC_*` variable**.

Start the UI:

```powershell
npm run dev
```

Default local UI origin: `http://127.0.0.1:3000`. The backend session/CSRF settings must recognize this origin. Browser-direct multipart uploads also require CORS on the selected SeaweedFS S3 bucket, configured separately. Platform setup and provider acceptance gates are documented in [the storage runbook](../infra/seaweedfs/README.md); frontend checks alone do not certify provider behavior. The previous MinIO cutover roadmap is historical.

## Verification

Poppins 400/500/600/700 is loaded through `next/font/local` from [the vendored original fonts and OFL](app/fonts/poppins/README.md). The font family, tokens and CSS variable stay the same; builds do not download Google Fonts. Install from the existing lockfile with `npm ci`; build dependencies still need their normal installation step.

```powershell
npx --no-install next typegen
npx --no-install tsc --noEmit
npm run lint
npm run build
```

### Focused unit tests

The following scripts are defined in `frontend/package.json` in the reviewed snapshot:

```powershell
npm run test:upload-manager
npm run test:auth
npm run test:account-security
npm run test:workspace-members
npm run test:preview-policy
npm run test:folder-download
npm run test:share-management
npm run test:admin-users
npm run test:admin-files
npm run test:admin-permissions
npm run test:admin-workspaces
npm run test:workspace-context
npm run test:admin-settings
```

Some Node test commands currently print `MODULE_TYPELESS_PACKAGE_JSON` warnings. That warning alone is not a test failure. Do not change the package-wide ESM mode without checking Next.js/configuration compatibility.

The repository includes `package-lock.json`. Use `npm ci` for a reproducible clean install; update the manifest and lockfile together when changing dependencies.

Browser regression tests use installed Chrome through Playwright. After the local API/UI are running and dedicated test sessions have been saved with `npm run test:e2e:auth`, run `npx playwright test mocked.spec.ts download.spec.ts admin.spec.ts system-review.spec.ts`. The admin suite is read-only. Live upload/download suites create their own fixtures and clean them up; see the feature reports before enabling them. Authentication state and generated test reports are ignored by Git and ESLint.

## Code structure

- `app/` — routes, layouts and pages (including administrative views).
- `components/` — UI components, including the drive browser and upload manager.
- `features/` — feature-specific modules; some directories are intentionally sparse after cleanup.
- `lib/` — API clients, access/policy helpers and tested utilities.
- `hooks/` — reusable hooks where present.

App Router pages may be used through route discovery rather than an explicit import. Never classify a page as unused solely because static import analysis finds no references.

## API and security boundaries

- `frontend/lib/account-service.ts` and `frontend/lib/drive-service.ts` use the configured `NEXT_PUBLIC_API_BASE_URL` for Django requests.
- Authenticated requests use browser session cookies (`credentials: "include"`) and CSRF handling for mutations.
- The active workspace header is *context selection*, not an authorization grant. Django must enforce permissions and tenant boundaries.
- Django authorizes every download. With direct download enabled, eligible S3 files use short-lived, version-pinned presigned GET URLs; legacy encrypted files, previews and ZIP archives use Django. Buckets remain private. Never log presigned URLs or upload credentials.

See [root README](../README.md) and [development guide](../docs/DEVELOPMENT.md).
