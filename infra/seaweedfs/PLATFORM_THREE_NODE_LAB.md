# BlueDrive Platform: Three Volume Server Docker Lab

The Platform owns its SeaweedFS cluster. UI **does not** offer manual connection setup or node creation;
Enterprise Storage Setup uses the existing separate workflow.

## Topology

`master` + `volume`, `volume2`, `volume3` + `filer` + PostgreSQL Filer metadata + `s3`.
Each `weed volume` container simulates a storage node. The existing `volume` service and
`volume_data` Docker named volume remain unchanged; two new named volumes are added.
All nodes are on the same Docker host — **not** physical fault tolerance or separate VMs.

## One-command Platform activation (recommended)

After `platform-seaweedfs-v1` Revision 2 is Verified (with successful Runtime Probe),
run from repo root in Windows PowerShell:

```powershell
& .\infra\seaweedfs\activate-platform.ps1                    # Preview; no write
& .\infra\seaweedfs\activate-platform.ps1 -Apply             # Deploy nodes, bind and enable routing
```

The script refuses to enable routing if all three Volume Servers are not registered
or if the Binding cannot be created using the verified connection.
It backs up `backend/.env` to Downloads (contains secrets; never share) and requires
restarting Django API and Finalizer after success. It does not delete accounts,
Workspace metadata, object data, or Docker volumes.

## Start without deleting existing data (manual alternative)

From repository root in Windows PowerShell:

```powershell
$Compose = '.\infra\seaweedfs\compose.yml'
docker compose -f $Compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Invalid compose configuration' }
docker compose -f $Compose up -d --no-deps master
if ($LASTEXITCODE -ne 0) { throw 'Cannot update Master port mapping' }
docker compose -f $Compose up -d volume volume2 volume3 filer s3 postgres
if ($LASTEXITCODE -ne 0) { throw 'SeaweedFS start failed' }
docker compose -f $Compose ps
(Invoke-RestMethod 'http://127.0.0.1:9333/dir/status').Topology.DataCenters | ConvertTo-Json -Depth 9
```

Do not use `down -v`, `docker volume prune`, or `git clean -fd`.
Volume slot capacity (`Max` / `Free`) is **not** disk byte capacity; /vol/status reports stored volume bytes. Physical disk metrics
require a dedicated host metrics source, not fabricated UI values.

## Prepare the already verified Platform Storage Connection

Revision 2 already passed actual S3 runtime checks. Use the management command instead of
manually clicking Prepare in the Platform UI:

```powershell
$Python = '.\.venv\Scripts\python.exe'
& $Python -X utf8 .\backend\manage.py prepare_platform_storage --operator bluedrive_admin
# If preview points to verified revision 2:
& $Python -X utf8 .\backend\manage.py prepare_platform_storage --operator bluedrive_admin --apply
```

Then check `PlatformStorageBinding` and, **only if successful**, set
`SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED=true` in `backend/.env`, restart
Django API and Finalizer and do a real My Drive and personal Workspace upload/download
smoke test. The management command does not modify environment flags or create S3 buckets.
The combined activation script above performs the checked flag update automatically.

## Operator UI

`/admin/infrastructure/topology` is the Platform live topology (Master `/dir/status`).
Each node is independently registered with the Master; absent expected nodes show Offline.
`/admin/infrastructure/connections` retains advanced diagnostics during rollout; it is
not the normal Platform admin workflow. Enterprise setup remains separate.

The Master API is reachable only via `127.0.0.1:9333` on Windows, and the Django API
checks permissions before fetching it. Never expose the unauthenticated Master API
publicly. HTTPS and host agents are required before Internet deployment.
