# BlueDrive Activity History & Search History patch

This patch addresses **visibility of existing history**; it does not recreate missing audit events.

## Scope

- Activity History: remove the action-type filter; server sorts newest first (`created_at DESC, pk DESC`). Keep double-click details modal.
- Fetch 50 records at a time and offer "Load older activity" and "Load older searches". Each list uses independent requests and error messages.
- Search History: display all stored search queries without applying the Activity date filter. Its records are in the `logs_searchhistory` database table, separate from ActivityLog.
- Django endpoints `/accounts/api/me/activity/` and `/accounts/api/me/search-history/` accept `offset` and return `hasMore`; old response keys (`events`, `items`) remain intact.
- Add a read-only diagnostics command with per-user counts. No data migration or destructive operation.

## Install (PowerShell from project root)

Back up/commit current source first. Stop Django and Next.js, then:

```powershell
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BlueDrive-Activity-History-Recovery-Fix.zip" -DestinationPath . -Force
python .\backend\manage.py check
python .\backend\manage.py test accounts.test_activity_history_pagination dashboard.test_search_activity files.tests.test_activity_log_transfers files.tests.test_download_security accounts.test_self_service_api -v 2
cd frontend
npm run build
```

Restart Django and Next.js. At Settings > Privacy: reset Activity date filters if set, click Refresh, and use "Load older activity" or "Load older searches". Rows are sorted newest first.

## Diagnose absent events (read-only)

```powershell
python .\backend\manage.py inspect_activity_history --username YOUR_USERNAME
```

Interpretation:
- SearchHistory > 0: existing queries should display in Search History. If zero, verify that searching from Drive creates a row. Cleared/deleted history cannot be inferred from ActivityLog if earlier metadata stored only query length; restore from a PostgreSQL backup if required.
- UPLOAD > 0: recorded successful uploads should appear in Activity History as pages are loaded. A historical successful upload **from before event recording was introduced** does not automatically become an audit event.
- Upload sessions in VERIFYING/SCANNING: start/verify the separate worker `python .\backend\manage.py run_upload_finalizer` and check its output. A successful multipart upload produces its UPLOAD event only after AVAILABLE publication.
- DOWNLOAD > 0: existing successful download events should appear as pages are loaded. A blocked/failed download intentionally creates no successful DOWNLOAD event.

This patch does not alter upload/download event creation paths because the latest source already records successful multipart finalization and successful single-file downloads; the actual database counts and worker state must be checked first.

## Validation scope

Verified locally: Python syntax, TypeScript/TSX syntax parsing, ZIP integrity. Full Django integration tests and Next.js production build require installed project dependencies and access to your test database. No migrations are needed.
