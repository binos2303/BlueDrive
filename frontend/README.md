# BlueDrive share-access test hotfix

## Why the original test failed
The `active_tenant_required` decorator returns 403 for authenticated staff accounts with no active tenant membership. That occurs before per-file access logic can produce 404. The original test expected 404 and 302 even though the request never reached the file view.

## Changes
- `backend/sharing/tests.py`: Update expectations to 403 for the staff-without-membership test, keeping mutation-safety assertions.
- Add a regression test for ACTIVE `PlatformAdminIdentity`: the platform-admin middleware must deny every Drive operation with 403.
- No changes to production code, permissions, database tables, quota or share logging.

## Apply
From SecureDrive project root (PowerShell):

```powershell
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BlueDrive-Share-Access-Test-Hotfix.zip" -DestinationPath "." -Force
python .\backend\manage.py test sharing.tests.SharingAccessTests.test_platform_staff_does_not_bypass_file_permissions sharing.tests.SharingAccessTests.test_active_platform_admin_is_blocked_from_drive_endpoints -v 2
python .\backend\manage.py test sharing.tests -v 2
```

## Verification
Python AST syntax checked; Django integration tests must be run on the user's Windows environment.
