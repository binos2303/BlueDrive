# Platform Storage Monitoring — Docker lab

## Scope and source of truth

The Platform Storage Dashboard at `/admin/infrastructure/topology` keeps the existing verified Storage Binding and **does not alter routing, buckets, quotas, or objects**.

| Data | Source | Interpretation |
|---|---|---|
| Registered/offline Volume Servers, allocated/free slots | SeaweedFS Master `/dir/status` | **Live registration**, not proof of data redundancy |
| Stored volume bytes, per-collection allocated volume records | Master `/vol/status` | Volume files, not S3 bucket object totals |
| CPU, RAM, cumulative network bytes, Docker health | Docker CLI collector on the **Windows host** | Container statistics; health checks are not end-to-end data operations |
| `/data` filesystem total/available | `docker exec <approved-volume> df -Pk /data` | Filesystem backing container's Docker volume; on Docker Desktop multiple volumes often share one disk |
| Browser upload/download health | Dedicated real upload/download smoke tests | Not inferred from online node counts |

The Django HTTP process **never executes Docker** and has no Docker socket access. Its Platform-admin-only endpoint reads a bounded, validated JSON snapshot from `infra/seaweedfs/.local/platform-metrics.json`. This path is ignored by Git and contains **no environment secrets**.

## Start monitoring on the Platform host

Open a **separate PowerShell terminal** in the repository root; leave Django and SeaweedFS running:

```powershell
cd 'C:\Users\dang2\Project\SecureDrive'

# Check that host Docker is accessible; this does not change containers.
docker compose -f .\infra\seaweedfs\compose.yml ps

# One snapshot, no persistent process
& .\.venv\Scripts\python.exe -X utf8 .\infra\seaweedfs\collect-platform-metrics.py --once

# Continuous sampling every 15 seconds (Ctrl+C to stop)
& .\.venv\Scripts\python.exe -X utf8 .\infra\seaweedfs\collect-platform-metrics.py --watch --interval 15
```

Each successful sample is atomically written in `.local`. Refresh the dashboard or allow its existing 10-second poll. **Data older than 60 seconds becomes `Stale`** and its metrics are not presented as fresh; errors are not overwritten with fabricated zeros.

For a permanent installation, replace this development collector with an authenticated internal monitoring agent / SeaweedFS Prometheus scraper. Don't grant the web server Docker daemon access just to populate charts.

## Operational alert semantics

- Master inaccessible → critical; registered node missing from topology → warning (only when Master is reachable).
- S3 root probe fails → warning; Docker `unhealthy` (from a fresh collector sample) → warning.
- Docker `/data` filesystem free below 10% → **one critical alert**, not one alert per volume server: multiple nodes may share the filesystem.
- Routing active without a verified Platform Binding → critical.
- No collector / stale metrics means **unknown**, not healthy. Current alerts are derived from samples and are **not persistent incident history**.

## Data safety

- Do not call `docker compose down -v` or delete any named volume.
- The UI's **Add Node** button provides an approved PowerShell command for the Platform lab; it does not execute arbitrary Docker commands in a web request.
- Dragging icons or rearranging topology never changes SeaweedFS placement.
- The **Copy Docker log command** action is read-only, for approved container names only.
- `volumes != files`, and free volume slots are not physical free disk capacity.

## Validation

```powershell
cd 'C:\Users\dang2\Project\SecureDrive'
& .\.venv\Scripts\python.exe -X utf8 .\backend\manage.py check
& .\.venv\Scripts\python.exe -X utf8 .\backend\manage.py test infrastructure.test_platform_live --noinput
& .\.venv\Scripts\python.exe -X utf8 -m unittest discover -s .\infra\seaweedfs -p 'test_collect_platform_metrics.py'
cd .\frontend
npx tsc --noEmit
npm run lint -- components/storage/PlatformClusterDashboard.tsx e2e/platform-storage-live.spec.ts
npx playwright test e2e/platform-storage-live.spec.ts --project=desktop --reporter=list
```

Smoke test My Drive and Personal Workspace upload/download separately after deployment. If the dashboard displays stale metrics, check collector terminal output first; do not change S3 credentials or Storage Binding as a workaround.
