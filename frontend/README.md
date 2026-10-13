# BlueDrive / SecureDrive Frontend

Next.js App Router frontend for the BlueDrive user workspace and administration console.

## Routes

- `/` redirects to `/login`
- `/login` sign-in UI
- `/register` account registration UI
- `/drive` user file workspace
- `/drive/shared` shared files
- `/drive/recent` recent files
- `/drive/starred` starred files
- `/drive/trash` trash
- `/admin` admin overview
- `/admin/activity` user activity and audit events
- `/admin/infrastructure` infrastructure health
- `/admin/permissions` roles, including scoped Team Leader permissions
- `/admin/backups` backup history and restore confirmation UI

## Development

```bash
npm install
npm run dev
```

## Integration notes

Login and registration use Django's existing session-cookie authentication. Copy `.env.example` to `.env.local` and set `NEXT_PUBLIC_API_BASE_URL` to the Django origin (for local development, `http://localhost:8000`). Open the frontend as `http://localhost:3000` as well; using `localhost` for both services keeps the CSRF/session cookies same-site. Restart Next.js after changing environment values. The browser sends credentialed requests and obtains a CSRF token from `/accounts/api/csrf/`. Login posts to `/accounts/api/login/` and then loads account context from `/accounts/api/me/`; registration posts to `/accounts/api/register/` and asks the user to sign in. No auth token is stored in JavaScript storage.

Next.js is the only user interface. Django no longer serves its HTML templates or Django Admin; its legacy page URLs redirect to Next.js (`/` and `/drive/*` to the matching Drive page, `/admin/` to `/admin`, `/accounts/login/` and `/accounts/register/` to authentication, and `/accounts/profile/` to `/account/profile`). Django REST endpoints return JSON only. Set Django's `NEXTJS_FRONTEND_URL` to the Next.js origin in production; it must be HTTPS. In development it defaults to `http://127.0.0.1:3000`.

For deployments, set exact frontend origins in Django's `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`; enable HTTPS, `SECURE_SSL_REDIRECT`, and Secure session/CSRF cookies. Same-site deployments can use the default `Lax` cookie policy. Cross-site frontend/API deployments require HTTPS and `SESSION_COOKIE_SAMESITE=None` plus `CSRF_COOKIE_SAMESITE=None`. Never use the development `.env.example` security values as production settings. Application-level rate limiting for public login and registration remains outstanding. Django's current user email column is not unique at the database level, so a reviewed cleanup/uniqueness migration is still required before relying on email as an unambiguous identity at SaaS scale.

The Drive and Admin screens still include sample data, and file/folder operations are not yet connected to frontend APIs. The Django APIs must enforce authentication, tenant scope, and role permissions; frontend navigation alone is not an authorization boundary.
