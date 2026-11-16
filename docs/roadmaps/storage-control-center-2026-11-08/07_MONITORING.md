# 07 — Live telemetry, health states and alerting

## 1. Sources
| Layer | Source | Measurements |
|---|---|---|
| Host | Enterprise Agent hoặc Prometheus node_exporter | CPU, RAM, NIC, mounts, disk free/errors, uptime |
| MinIO node | AIStor/MinIO version-specific metrics | Per-node online, process, I/O, errors, drive health |
| Cluster | `/minio/health/cluster`, `/cluster/read`, Prometheus metrics | write/read quorum, offline count, healing, capacity |
| BlueDrive | Django/worker metrics | presign failures, upload finalization backlog, quota drift, retry/error |

MinIO `GET /minio/health/live` thể hiện tiến trình phản hồi, **không đủ** kết luận mọi peer hoạt động. Health/read/write quorum và node exporter bổ sung cho nhau. AIStor metrics v3; Community legacy có v2; chọn đúng exporter/query theo edition.

## 2. Status model
- `HEALTHY`: metrics và health current, không có critical alerts, cluster read/write ready.
- `DEGRADED`: đủ quorum nhưng >=1 node/drive lỗi, healing, latency, capacity warning.
- `CRITICAL`: mất quorum hoặc có alert critical được xác minh.
- `OFFLINE`: agent/MinIO/node đã được xác nhận down theo nhiều nguồn và threshold.
- `UNKNOWN`: collector lỗi, chưa có samples, timestamp stale, network partition chưa phân biệt với host failure.
- `MAINTENANCE`: authorized planned job đang chạy (không đồng nghĩa healthy).

Mỗi badge bắt buộc có `status, observed_at, source, last_success_at, stale, reason_code`. Nếu metrics ngắt, show last known sample kèm stale label, không tô xanh tiếp.

## 3. Collection / storage
- Scrape interval 15–30s (configurable), heartbeat 10–15s, stale 3 missed heartbeats (baseline, cần đo thực tế).
- Current summary/status trong PostgreSQL với short retention; time-series raw trong Prometheus/TSDB có retention; không ghi từng tick CPU vào table PostgreSQL ứng dụng.
- UI SSE gửi delta event `cluster_id,node_id,observed_at,status,revision`; reconnect with cursor/last-event-id then refresh snapshot. Browser not direct scrape private node metrics.
- Metrics không mang object key đầy đủ, token, dữ liệu định danh khách hàng ngoài tenant scope.

## 4. Dashboard metrics
Node inspector: CPU %, RAM used/available, filesystem free bytes, network Rx/Tx, process uptime, MinIO version, drives healthy/warning/offline, healing progress (nếu có).
Cluster: read/write quorum, node count online/unknown, failed disks, raw vs usable vs logical storage, pending jobs and last backup verification separately.

## 5. Alerts
| Severity | Trigger example | Action |
|---|---|---|
| Warning | 70–80% forecast capacity hoặc error rate tăng | Alert organization storage admin |
| Critical | Không đủ write quorum, disk failures, checksum mismatch | Block unsafe operations, incident |
| Warning | Metrics stale > threshold | Status UNKNOWN, notify collector issue |
| Critical | Agent revoked/compromised suspected | Rotate/revoke credentials, freeze operations |
| Warning | Worker cleanup backlog increased | Report operation health / reconcile |

Ngưỡng là cấu hình, không phải universal SLA. Dedupe alerts + cooldown; lịch sử và acknowledge có actor/timestamp.

## 6. SLO measurement
- Monitor `scrape_success`, freshness, SSE delivery, API p95/p99, dashboard render time.
- Chứng minh alert real by killing isolated dev node/agent or blocking collector, không gán điều kiện lỗi giả vào dashboard production.
- Không chỉ dựa vào GUI demo: đối chiếu raw metrics source và output API, có screenshot/timestamp + trace ID.
