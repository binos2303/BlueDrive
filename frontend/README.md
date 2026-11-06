# BlueDrive frontend

This directory is the **Next.js 16 App Router** frontend for personal drives, workspaces, account settings and the platform administration console. It uses React 19, TypeScript and Tailwind CSS 4.

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

This public environment variable identifies the Django API origin. It is compiled into browser code, so **never put credentials, API secrets or storage keys in any `NEXT_PUBLIC_*` variable**. An optional `NEXT_PUBLIC_SUPPORT_URL` can point to a configured support destination; it is not a substitute for a backend ticket system.

Start the UI:

```powershell
npm run dev
```

Default local UI origin: `http://127.0.0.1:3000`. The backend session/CSRF settings must recognize this origin. The actual browser-direct MinIO multipart flow also requires appropriate *MinIO bucket CORS*, configured separately.

## Verification

```powershell
npx tsc --noEmit
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
npm run test:admin-teams
npm run test:admin-settings
```

Some Node test commands currently print `MODULE_TYPELESS_PACKAGE_JSON` warnings. That warning alone is not a test failure. Do not change the package-wide ESM mode without checking Next.js/configuration compatibility.

The reviewed source export did **not** include an npm lockfile. `npm install` can therefore resolve newer versions permitted by `^` constraints; a separate dependency-management task should introduce and verify a committed lockfile. Do not assume `npm ci` works until that is done.

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
- Download/preview content is served through Django, not as a public MinIO URL. Never log presigned URLs or upload credentials.

See [root README](../README.md) and [development guide](../docs/DEVELOPMENT.md).
