# BlueDrive Storage Control Center — S4 monitoring và scoped SSE

Ngày: 09/11/2026. Nhánh: `feature/storage-control-center-s4-20261109`.

## Kết quả

Đã triển khai phần mã S4: collector Prometheus chỉ đọc qua profile operator, snapshot có freshness/provenance, incident alerts và ACK có audit, REST/SSE giới hạn theo tenant, cùng giao diện monitoring trên topology dùng chung Platform/Organization.

**Backend558 bài:549 PASS,9 MinIO integration SKIP. Chrome82/82 PASS; Node7/7 PASS; TypeScript, ESLint toàn frontend, production build39 trang và Django check/migration drift PASS.** Đã áp dụng riêng additive migration0005 lên PostgreSQL local sau backup archive được kiểm tra; không sửa .env, không bật cờ, không khởi chạy collector thật.

**Chưa nghiệm thu MinIO/exporter/Prometheus thật hoặc SSE qua ASGI/reverse proxy vận hành. G2/G4 vẫn mở; không coi kết quả fixture là hoàn thành roadmap toàn hệ thống.** Giống bảng theo dõi kho: phần đọc và trình bày số đo đã được kiểm tra, nhưng vẫn cần kiểm định cảm biến và đường truyền tại kho thật trước đưa vào trực vận hành.

## Quyết định và phạm vi

Dùng skill ponytail, impeccable và workflow Storage Control Center đi kèm roadmap. Đọc source hiện tại và hướng dẫn S4 trước quyết định; giữ design system và transport S2. Chọn một summary hiện tại trong PostgreSQL, raw history tại TSDB, một snapshot/cluster thay vì polling từng node. Profile/query chỉ cấu hình phía server; không thêm API cho browser nhập URL, PromQL hay secret.

Hướng này tái sử dụng tenant boundary, connection network policy, Button/Dialog/tokens và Canvas hiện có. Tự tạo database time-series hoặc proxy Prometheus tự do sẽ thêm trách nhiệm vận hành và bề mặt truy cập. SSE chỉ bật khi request thực sự đi qua ASGI; WSGI dùng polling thay vì giữ một thread dài cho mỗi người xem. Xem ADR-0005 và runbook kèm theo để vận hành sau gate.

## Những gì thay đổi và vì sao

| Nhóm file | Sửa/triển khai | Lý do |
|---|---|---|
| `infrastructure/models.py`, migration0005 | StorageTelemetrySnapshot và StorageAlert, TTL bounds, active-incident uniqueness, protected cluster | Tách summary khỏi raw time-series, dedupe incident và giữ lịch sử/actor |
| `infrastructure/prometheus.py` | Profile đúng scope/edition/version, expression + timestamp_expr, allowlisted metrics/labels, TLS/CIDR/socket pin, bounded queries/body/deadline | Không đoán exporter version, không nhận dữ liệu tenant khác hoặc lấy HTTP time làm freshness |
| `connection_profiles.py` | Tách pool factory dùng chung cho S2 và monitoring | Một cơ chế pin mạng/TLS cho cùng bài toán; S2 transport/TLS regression vẫn đạt |
| `infrastructure/telemetry.py` | Generation/profile fencing, khóa snapshot khi claim/publish, kiểm tra timestamp/giá trị, stale sweep và incident recovery | Kết quả chậm không ghi đè kết quả mới; collector lỗi không giữ Healthy hoặc xóa incident critical |
| `telemetry_api.py`, URLs/capabilities | Snapshot, ASGI SSE resync, incident history và ACK versioned/CSRF/audit | Monitor permission tách khỏi view/configure; session/quyền được kiểm tra lại, không lộ source URL/token |
| `collect_storage_telemetry` | Một lượt hoặc watch chủ động, interval15–60s, lỗi scope/profile được báo bằng code an toàn | Không tự khởi chạy tiến trình trên hạ tầng người dùng; operator có bước kiểm soát rollout |
| `StorageMonitoring`, `useStorageTelemetry`, model | Current/last-known values, observed/source, local expiry, native EventSource resync, polling fallback, ACK note | Lỗi/mất mạng/thu hồi quyền có phản hồi rõ, thiếu dữ liệu không thành0 |
| `StorageTopology`, Canvas, Inspector, shared service | Overlay health/metrics vào card/List/inspector, giữ nguyên vị trí/selection/filter khi telemetry đổi | Cập nhật trạng thái không làm mất bố cục chưa lưu hoặc tạo request theo từng node |
| S3/S4 shared E2E fixture | Tách fixture inventory dùng lại | Hai bộ kiểm thử dùng cùng mô hình và API expectations, tránh drift |
| ADR/API/data model/runbook/progress/README | Đồng bộ contract, schema, rollback và gate | Phân biệt code đã làm với dữ liệu thật/vận hành còn thiếu |

Danh mục file và SHA-256 trong `source-changes.json` chỉ gồm phạm vi S4 được lựa chọn; không coi toàn bộ dirty Git diff là thay đổi lượt này. Không reset/stash/clean/stage/commit thay đổi cũ, không tạo PR từ dirty tree.

## Sửa lỗi xác nhận được trong triển khai

- Acceptance đầu tiên xác nhận endpoint chưa có bằng404; sau triển khai kiểm tra unknown/no I/O, monitor permission, tenant boundary và flag-off đều đạt.
- Test ACK phát hiện event ghi đồng thời cluster và tenant vi phạm ownership constraint hiện có. Sửa sử dụng cluster-owned audit như các mutation cùng domain; retry ACK không tạo audit thứ hai.
- Rà soát concurrency phát hiện claim khóa cluster nhưng chưa khóa snapshot trước read/modify/save. Một publisher có thể cập nhật snapshot trong khoảng đó. Test trước sửa FAIL do thiếu SELECT FOR UPDATE; thêm khóa snapshot, toàn bộ558 bài sau sửa đạt. Đây là bằng chứng SQL lock và generation fencing, không phải load test nhiều collector thật.
- Xem screenshot phát hiện nhãn inventory Health unknown gây mâu thuẫn với monitoring. Đổi header sang ghi rõ recorded pools/nodes/disks khi monitoring đang dùng; trạng thái nằm tại panel có provenance. Kiểm tra lại bằng build và82 bài Chrome cuối.

## Kiểm chứng

| Kiểm tra | Kết quả/bằng chứng |
|---|---|
| Full backend cuối |558 bài,549 PASS/9 SKIP; `backend-acceptance/django_a01_a10.txt` và isolation.json |
| Source timestamp | Mẫu gốc cũ bị từ chối dù Prom evaluation time mới; success join timestamp đúng; missing/foreign/duplicate/nonfinite bị chặn |
| Fencing/freshness/alerts | Lượt cũ bị từ chối, profile revision xung đột, timestamp đi lùi, giữ last-known và critical incident khi lỗi, stale dedupe, recovery resolve |
| API/ASGI | Cross-tenant404, inventory-only403, flag404, CSRF403, ACK conflict/idempotency/audit, ASGI stream thực qua Django AsyncClient, cursor sai400, grant/session/password invalidation |
| Transport | Redirect/auth/body/deadline failures và sanitized errors; hồi quy DNS rebinding, proxy, CIDR và TLS loopback thật của S2 đạt |
| Chrome cuối |82 PASS =44 UI regression +10 Connections +18 Topology +10 Monitoring; desktop1440×900 và mobile390×844, fixture API chặn request chưa định nghĩa |
| UI monitoring | Network error giữ512GiB nhưng Unknown/Stale; clock expiry, ACK vẫn active, Organization inspector CPU/RAM, native EventSource resync, clearing after403, không polling node, không mất vị trí chưa lưu |
| UI/ảnh | Đã xem ảnh desktop/mobile cho trạng thái stale và inspector; bộ hồi quy còn có dark320px,720px và chuột/touch emulated; không thay physical-device/screen-reader nghiệm thu |
| Node |7/7 PASS:5 topology model và2 expiry/missing-node health |
| Frontend | TS noEmit, ESLint toàn frontend và Next16.3.3 production build39/39 PASS; build exit0 riêng, snapshot không chứa .env/auth |
| Local schema | Backup archive pg_restore --list thành công; chỉ migration infrastructure0005; Django check PASS, makemigrations --check --dry-run không drift |

Backend chạy trên PostgreSQL cluster/DB riêng tạo mới cho mỗi lượt, loopback/media/email tạm; chặn storage và monitoring HTTP chưa mock. Cluster tạm đã dừng và xóa đúng thư mục do runner tạo. Chín MinIO integration SKIP do chưa mở môi trường thật. Chrome dùng server production riêng cổng3013, đã dừng sau kiểm tra, không dùng/sao chép phiên đăng nhập người dùng. Các ca monitoring dùng dữ liệu fixture, không có telemetry giả trong runtime.

## Migration, cấu hình và rollback

Local schema đã ở infrastructure0005. Backup DB riêng nằm trong thư mục artifact gitignored và **không xuất vào Downloads**. Chỉ thêm hai bảng; không backfill file, đổi quota, binding hoặc object storage. Các cờ Storage Control Center/Topology/Monitoring/routing/operations/LAB giữ OFF; .env không đổi. Web/finalizer thật hiện có không bị khởi động lại.

Rollback bằng tắt monitoring flag và dừng collector do operator quản lý; giữ bảng/history. Không cần reverse migration, xóa incident hoặc rollback S2/S3. Thay profile phải tăng revision và duyệt lại; không giảm revision để ép nhận kết quả cũ. Chi tiết cấu hình và bước G4 nằm trong S4_RUNBOOK.md.

## Phần còn lại

1. **G2/G4:** duyệt edition/license/version, danh tính read-only, TLS/CIDR/labels và bộ query/timestamp thực; đối chiếu quorum/host/capacity bằng raw source. Chưa có profile nào được tự tạo hoặc cờ nào được bật.
2. **Triển khai runtime:** chọn ASGI server, process supervisor cho collector, TSDB retention, reverse proxy SSE và giới hạn/tải nhiều client. Chưa đo p95/p99 API/SSE vận hành hoặc cam kết SLA30s. DNS dùng resolver hệ điều hành; deadline HTTP không thay kiểm chứng vận hành DNS trên host thật.
3. **Chức năng ngoài lượt:** UI lịch sử incident/biểu đồ raw metric, thông báo ra email/Slack, healing/backup/worker metric chưa có exporter được duyệt; không giả số liệu. Lịch sử incident hiện có REST phân trang. Stale badge hoạt động độc lập; stale incident chỉ được materialize lúc collector sweep, chưa có watchdog riêng nếu cả collector dừng.
4. **S5–S8:** agent enrollment/mTLS, provisioning, maintenance/pool lifecycle, restore drill và rollout chưa triển khai. Phải qua gate hạ tầng tương ứng, không suy từ test fixture.
5. Các risk cũ A03 permanent-delete DB/S3 atomicity và A04 in-flight orphan races không được đóng bởi S4.

Có thể bổ sung pattern kiểm chứng source timestamp → scope → stale → ACK → SSE vào Agent Skill Storage Control Center hiện có để dùng lại; không cần tạo thêm skill trùng chức năng.

Đối chiếu kỹ thuật: [Prometheus query API](https://prometheus.io/docs/prometheus/latest/querying/api/), [timestamp()](https://prometheus.io/docs/prometheus/latest/querying/functions/#timestamp), [Django async streaming](https://docs.djangoproject.com/en/5.2/ref/request-response/#django.http.StreamingHttpResponse).
