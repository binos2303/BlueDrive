BlueDrive User Management compact summary patch

Based on BlueDrive-Admin-Quota-Consistency-Fix.zip.
Modified: frontend/components/admin/UserDirectory.tsx

- Move Regular Users / Platform Admins tab switcher inside the table card, above the filters.
- Display only Total users on Regular Users tab, Total admins on Platform Admins tab.
- Remove separate summary panel with Active/Disabled/Platform admins values.
- Keep user search, filters, sort, pagination, admin actions and backend APIs intact.

Apply in the project root (PowerShell):
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BlueDrive-User-Summary-Compact-Hotfix.zip" -DestinationPath . -Force
cd frontend
npm run build

No migration or backend changes.
