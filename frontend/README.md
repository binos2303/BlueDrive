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

The current screens use sample data. Login, registration, metrics, role changes, audit queries, backup, and restore are not connected to Django APIs yet. Enforce authentication and role permissions on the backend; frontend navigation alone is not an authorization boundary.
