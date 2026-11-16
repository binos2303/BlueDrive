# 04 — Domain, database & API contracts (PROPOSED, not existing routes)

## 1. Entity map — minimum viable
| Model | Trường bắt buộc đề xuất | Constraints |
|---|---|---|
| `StorageCluster` | id, tenant_id, kind(platform|enterprise), display_name, provider, edition, provider_version, state, health, observed_at | tenant FK + unique slug per tenant; no ownerless cluster |
| `ServerPool` | id, cluster_id, name, generation, desired_status | cluster FK; unique(pool name, cluster) |
| `StorageNode` | id, cluster_id, pool_id(nullable), agent_identity, hostname, private_ips, labels, state, last_seen | immutable UUID, agent unique; IP không là PK |
| `NodeDisk` | id, node_id, stable_disk_id, mount_path, capacity, state, last_seen | unique(node, stable_disk_id) |
| `StorageBinding` | id, tenant_id, scope(tenant|workspace), workspace_id, storage_config_id, state, active_since, generation | một active binding/scope; cross-tenant FK validation |
| `TopologyLayout` | id, tenant_id, cluster_id, owner_user_id(optional), revision, positions JSON, viewport JSON | optimistic concurrency; chỉ tọa độ |
| `ClusterOperationJob` | id, tenant_id, cluster_id, kind, state, plan_hash, requested_by, approved_by, expires_at, lease_version, error_code | idempotency key per tenant/type, audit |
| `ClusterAuditEvent` | id, tenant_id, actor, action, resource_ref, before, after, reason, timestamp | append-only API |

`StorageConfig` đã tồn tại, liên kết `Tenant` và `StorageLocation`; không được tạo model mới chép toàn bộ fields của nó. `StorageCluster` là **inventory/topology**, `StorageConfig` là **S3 client connection config**, `StorageBinding` là **policy chọn nơi lưu**.

## 2. Mandatory compatibility migrations
- `StorageConfig` hiện có UniqueConstraint `(tenant,provider)`; MVP 1 config/tenant/provider không đòi bỏ constraint. **Trước nhiều MinIO cluster trong một tenant**: cần thay constraint, migrate dữ liệu và update mọi queryset assume singleton, tạo unique `active binding` mới.
- `UploadSession` hiện không có `storage_config_id`: thêm nullable -> backfill theo data mapping đã xác nhận -> mới require ở new session. Idempotency/complete/worker/cleanup dùng cùng StorageConfig pinned tại initiation. Đối với session cũ chưa có ref, dùng legacy resolver có kiểm soát, không tự đoán cluster.
- `StorageLocation` giữ object ref và provider_version_id; immutable committed version reference; không rewrite để đổi cluster.
- Đổi bind chỉ ảnh hưởng **upload mới**. Download object cũ vẫn đọc theo StorageLocation cũ. Thao tác migration phải là job riêng.

## 3. API mẫu (version `v1` đề xuất, không có trong source)
Base: `/api/v1/storage/` và `/api/v1/platform/storage/`; routes nên theo conventions existing `accounts/urls.py`.

**Read:**
- `GET /clusters?scope=organization` -> paginated list, tenant implicit from session/permission.
- `GET /clusters/{id}` -> cluster info + health summary + observed_at.
- `GET /clusters/{id}/topology` -> `revision, pools, nodes, disks`, no credentials.
- `GET /clusters/{id}/nodes/{nodeId}` -> details and last observation.
- `GET /clusters/{id}/events?cursor=...` -> audit/events.
- `GET /clusters/{id}/telemetry?node_id=...&window=...` -> aggregate (time-window bounds).
- `GET /clusters/{id}/stream` -> SSE (authorize connect, per-message scoped event).

**Inventory/control:**
- `POST /clusters/connect` -> create scoped DRAFT; URL checked against explicit allowlist/policy.
- `POST /clusters/{id}/verify` -> read-only S3/health verification; active status only after checks.
- `POST /clusters/{id}/hosts/enrollment` -> one-time enrollment challenge.
- `PATCH /clusters/{id}/layout` -> `{expected_revision,positions,viewport}`; only UI layout.
- `POST /clusters/{id}/plans` -> proposed operation and target inventory (no mutation).
- `POST /clusters/{id}/plans/{planId}/validate` -> preflight.
- `POST /clusters/{id}/plans/{planId}/approve` -> approval/reason/time-bound token.
- `POST /clusters/{id}/plans/{planId}/execute` -> async job only.
- `GET /operations/{jobId}` -> job status and progress.
- `POST /operations/{jobId}/cancel` -> only if safe stage; never promise undo of S3 deletion.

## 4. Response envelope example
```json
{
  "cluster_id": "uuid",
  "topology_revision": 7,
  "observed_at": "2026-11-08T10:00:00Z",
  "health": {"status": "unknown", "source": "agent", "stale": true},
  "pools": [{"id":"pool-uuid","name":"Pool 1","node_ids":["node-uuid"]}],
  "nodes": [{"id":"node-uuid","hostname":"storage-01","status":"unknown","last_seen":null}]
}
```
No fake live data. Error codes e.g. `storage_not_reachable`, `node_not_enrolled`, `cluster_conflict`, `topology_revision_conflict`, `operation_preflight_failed`, `quorum_insufficient`, `storage_binding_immutable_for_active_upload`.

## 5. RBAC/API access
- `platform.storage.*`: platform-owned resources only, except explicit support grant.
- `organization.storage.view|monitor|configure|operate|approve`: own tenant only; separate role from Org Admin content ACL where necessary.
- Workspaces and users: no infrastructure operations by default.
- Never trust `tenant_id` in client body; derive target tenant from authenticated route + membership + backend object ownership.
- `GET` id not found or other tenant must avoid cross-tenant leaks (404-style), audit attempts.
- Rate limit control plane, enforce CSRF for session-auth mutations and reauthentication/step-up for destructive operations.

## 6. Control state machine
`DRAFT -> VALIDATING -> READY -> AWAITING_APPROVAL -> APPROVED -> RUNNING -> VERIFYING -> SUCCEEDED`
Error: `VALIDATING/RUNNING/VERIFYING -> FAILED / NEEDS_ATTENTION`; cancel only in cancellable phases; expired plan -> EXPIRED. Retries must be idempotent and fenced with `lease_version`, not just timestamp.

## 7. Database tests
- Unique active tenant binding / workspace binding; single active operation per cluster if incompatible; onboarding token unique and expires.
- Distinct Organization cannot read/update each other's cluster, node, telemetry, agent registration, job.
- 2 transaction connections: racing plans, approvals, binding flips, upload sessions pin same cluster; failover does not delete old StorageLocation.
- Deleting tenant must not CASCADE physically delete provider data; tombstone and retention workflow.
