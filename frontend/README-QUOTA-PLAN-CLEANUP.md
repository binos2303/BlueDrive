# BlueDrive: quota plans and sharing-size removal

## Changes

- Quota Plans now have `Delete` actions (Super Admin only, reason 8-500 characters, audited).
- The `free` and `workspace-starter` plans cannot be deleted or disabled.
- Assigned plans cannot be deleted: quota allocations and plan references are preserved.
- Plan directory shows active plans by default; `Show inactive` reveals archived ones.
- Existing plan cleanup is an explicit management command, dry-run by default.
- Share-size policy controls and enforcement are removed for direct file and folder sharing.
- Warning/critical quota thresholds remain configurable at `/accounts/api/admin/quota-policy/`.
- The old `StoragePolicy.max_personal_file_bytes` column is **retained but ignored** for historical compatibility; it is no longer read by share endpoints or editable through the API. No migration needed.
- Plan audit history is preserved. New events record plan deletions and archival.

## Install (project root on Windows PowerShell)

Before applying: commit or back up code and PostgreSQL. Close Django, Next.js and workers.

    Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BlueDrive-Quota-Plan-Cleanup-Fix.zip" -DestinationPath "." -Force

Then validate:

    python .\backend\manage.py check
    python .\backend\manage.py makemigrations --check --dry-run
    python .\backend\manage.py test accounts.test_admin_plan_policy accounts.test_quota_management sharing.tests -v 2
    cd frontend
    npm run build

## Clean obsolete plan presets

The code patch itself does **not** change database plan rows.
Run the dry-run first from the project root:

    python .\backend\manage.py prune_storage_plans

After inspecting the output and backing up PostgreSQL, apply it as your Super Admin:

    python .\backend\manage.py prune_storage_plans --apply --actor YOUR_SUPERADMIN_USERNAME

Only `free` and `workspace-starter` will remain active. Other unassigned
presets are **deleted**, while assigned presets are disabled and hidden
from the active list. Assigned quota limits, references and files remain unchanged.
The command is repeatable. `Show inactive` can reveal assigned legacy presets.

## Limitations

- Integration tests and production Next.js build were not run in this container.
- The new API endpoints require the latest matching frontend and backend; restart both.
- This does not reassign old quotas to Free or Workspace Starter or change the default
  quota for newly created accounts/workspaces. Existing quotas remain as configured.
- Historical direct-sharing size settings stay in an unused DB column; no restriction is applied.
