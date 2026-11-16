# 08 — QA, acceptance and fault-injection matrix

## 1. Test environments
- `UNIT`: pure logic / mocked MinIO; không kết luận availability thật.
- `INTEGRATION`: PostgreSQL test DB riêng + MinIO riêng/bucket mới; MinIO test credentials không trùng dữ liệu thật.
- `STAGING`: nhiều VM Linux và agent; topology rõ; chọn edition/release đã pin.
- `PRODUCTION`: chỉ read-only monitoring / canary sau khi release gates đạt.

## 2. Matrix by sprint
| Case | Trigger | Expected | Evidence |
|---|---|---|---|
| RBAC-01 | User A GET cluster tenant B | 404/403 scoped, no data | Django API test + audit |
| RBAC-02 | Org Admin POST create Organization | denied | API test |
| RBAC-03 | Platform Admin uses org root storage action without grant | denied | API test |
| UI-01 | Drag registered node to new X/Y | only layout saves | Browser E2E + DB diff |
| UI-02 | Click node | inspector displays real timestamp/source | Browser E2E |
| UI-03 | Agent stops sending metrics | UNKNOWN/stale, not HEALTHY | Integration + mocked time |
| UI-04 | Keyboard and touch on topology | select, pan, inspector accessible | Playwright + real device |
| INV-01 | Register two nodes with same agent identity | unique conflict | PostgreSQL transaction |
| INV-02 | Rename node with IP collision | disambiguation / validation | API test |
| BIND-01 | Switch active binding during upload | pinned old target until complete | two-connection DB + MinIO test |
| BIND-02 | Download old version after new binding | reads old `StorageLocation` | API + checksum |
| JOB-01 | Two approval requests same plan | one effective approval | two DB connections |
| JOB-02 | Worker loses lease during storage call | stale completion fenced | concurrent worker tests |
| AGENT-01 | One-time enrollment token replay | deny replay | integration |
| AGENT-02 | Forged tenant/expired signed plan | reject | integration |
| AGENT-03 | Duplicate message delivered after action | idempotent result | fault inject |
| MINIO-01 | S3 timeout after successful PUT | verify exact version/checksum, no double publication | Toxiproxy isolated |
| MINIO-02 | Node down but write quorum remains | DEGRADED, operation safe policy | staging only |
| MINIO-03 | Insufficient write quorum | CRITICAL, unsafe maintenance denied | staging only |
| MINIO-04 | New pool incompatible EC policy | plan validate FAIL, no install | preflight test |
| MINIO-05 | Decommission target active but not enough capacity | reject | safe dry_run |
| SEC-01 | Arbitrary URL/IP in connect wizard | cannot SSRF internal endpoints | API + network mock |
| SEC-02 | Secret appears in API/log | zero leaks | log scan |
| BACKUP-01 | DB + objects + keys restore | checksum/version metadata verified | restore drill |

## 3. Release gates
G0 baseline green, test isolation documented; G1 tenant scoped read-only cluster inventory; G2 browser S3 connectivity and signed URL policy; G3 telemetry freshness; G4 agent signed tasks; G5 dry-run deploy; G6 verified fault handling, backup/restore; G7 controlled production canary.

## 4. Benchmark profiles
- Dataset: 1 / 10 / 50 / 100 / 500 nodes (beyond actual, use synthetic UI data clearly marked), 1 / 10 / 100 workspaces, separate large audit logs.
- Scenario: canvas pan/zoom/drag, 1s telemetry events, 10 concurrent admins, high-latency API, disconnected agent, staggered error traffic.
- Measure browser FPS, TTI, React re-render count, API p50/p95/p99, DB queries, SSE gap, memory footprint. Set budget based on baseline hardware, do not assert numbers before tests.
- Stress storage data paths separately from canvas; no endpoint-only high-load tests on enterprise production.

## 5. Test-result classifications
- `PASS`: acceptance verified with evidence.
- `FAIL_CONFIRMED`: invariant violated (keep log/repro).
- `NOT_REPRODUCED`: bounded conditions, no claim universal safety.
- `BLOCKED`: environment unavailable, dependency failing, legal/edition not approved.
- `NOT_RUN`: no execution evidence.

## 6. No false green
- A test response mocked at browser layer cannot certify MinIO or node health.
- Ping/health endpoint 200 cannot certify drive correctness or read/write quorum.
- Simulated 4-node laptop can't certify production HA.
- Avoid modifying test fixtures to artificially make tests pass; document failures and remediation.
