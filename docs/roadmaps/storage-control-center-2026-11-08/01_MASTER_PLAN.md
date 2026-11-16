# 01 — Master Implementation Plan

## 0. Problem statement
BlueDrive có My Drive/Workspace, Django API, MinIO adapter, quota và worker; nhưng giao diện topology hiện chỉ là placeholder, backend adapter là global singleton từ settings. Chưa có quản lý cluster/node, đa storage routing, telemetry và enterprise provisioning. Cần thêm Storage Control Center theo từng tenant **mà không phá upload/download/quota đang ổn định**.

## 1. Product boundaries (đã chốt)
- Platform-only **tạo Organization**, chỉ định owner, suspend organization. Không có self-create endpoint cho user.
- Organization Owner/Admin: quản lý Workspace và quota, có quyền quản lý storage khi được cấp role `storage_admin` hoặc quyền tương đương. Không mặc nhiên đọc mọi file chỉ nhờ quyền quản lý hạ tầng.
- Platform Admin quản lý **cluster của Platform**, không tự động đọc dữ liệu hoặc dùng root key của doanh nghiệp. Hỗ trợ chéo tenant cần ủy quyền ngắn hạn và audit.
- Personal My Drive lưu trên storage Platform. Business Workspace lưu trên storage binding hợp lệ của Organization. Trong MVP: một cluster active cho mỗi Organization; chuẩn bị thiết kế nhiều cluster nhưng không bật routing đa cluster ngay.
- Tất cả control operations có audit, idempotency, validation, concurrency control, compensation; không cung cấp nút xóa vật lý trực tiếp.

## 2. Sprint chain & gates

### S0 — Baseline & safety (không thay đổi sản phẩm)
**Đầu vào:** Source hiện tại, test hiện có, Docker/VM dev, PostgreSQL test, MinIO test cô lập.
**Việc làm:** dựng map API/route/model; ghi lại Django tests / TS build / Playwright baseline; xác định các trạng thái StorageConfig/StorageLocation/UploadSession; scan secret theo nội dung; kiểm kê current MinIO edition/version; thiết lập feature flag OFF; đăng ký công cụ chạy test và rollback.
**Nghiệm thu:** báo cáo code-map, test baseline, không thay đổi production DB, không copy auth state vào artifact; các quyết định license/edition có chủ sở hữu.

### S1 — Inventory domain + RBAC (MVP data)
**Việc làm:** StorageCluster, StorageNode, ServerPool, NodeDisk, StorageBinding, TopologyLayout, StorageAuditEvent, ClusterOperationJob (có thể gộp theo nghiệp vụ, tránh vụn file); migration bảo toàn StorageConfig hiện tại. Cấp `storage.view`, `storage.configure`, `storage.operate`, `storage.approve`, `storage.monitor`, giới hạn theo tenant.
**Nghiệm thu:** foreign key/constraints; test user A không xem tenant B; Platform quản lý own clusters; Org Admin không tạo tenant; Test migration up/down trên bản backup test; unknown cluster không được bind.

### S2 — Connect Existing Cluster (READ ONLY trước)
**Việc làm:** UI kết nối endpoint S3 đã có, nhận fingerprint/certificate/credential reference, server-side validation; verify bucket/object bằng fixture isolated; đọc thông tin version/health hỗ trợ. Credentials không gửi về browser.
**Nghiệm thu:** kết nối thành công một cluster test; host/IP whitelist qua agent/allowlist, không SSRF; lỗi TLS/credential/timeout trả chính xác; không dùng minio root credentials của doanh nghiệp trong Platform.

### S3 — Interactive Topology Canvas
**Việc làm:** React Flow trong Next client boundary; canvas có pan/zoom/minimap/fit, pool grouping, custom node, right inspector, search, filters, keyboard, auto-layout; lưu vị trí riêng với topology. Platform và Org chia sẻ UI.
**Nghiệm thu:** drag không thay đổi node topology; reload giữ layout; thay trạng thái không đổi layout; empty/error/stale/loading; không overflow 320px/200% zoom; 100 node vẫn tương tác mượt theo benchmark browser.

### S4 — Monitoring thật
**Việc làm:** ingest MinIO metrics theo edition; host metrics từ agent/node exporter; snapshot current state + lịch sử tại TSDB có retention, không nhồi raw samples vào PostgreSQL; SSE có reconnect/resync; các health trạng thái có observed_at và source.
**Nghiệm thu:** không fake metrics; node chết->UNKNOWN khi mất monitoring, OFFLINE chỉ khi đủ chứng cứ; tổng cluster có read/write quorum; alert khi disk lỗi, quorum giảm, collect stale; metrics có tenant filter.

### S5 — Enterprise Agent & enrollment
**Việc làm:** agent chủ động kết nối ra control plane qua TLS/mTLS; enrollment one-time token; allowlisted task schemas; signed payload/replay protection; local privilege separation; audit, rotate/revoke; installer có package checksum/signature.
**Nghiệm thu:** token tái sử dụng bị từ chối; giả mạo tenant/agent bị chặn; không có remote arbitrary shell; mất kết nối vẫn không khiến agent chạy lại nguy hiểm; audit đầy đủ.

### S6 — Provisioning wizard (LAB ONLY)
**Việc làm:** flow draft→enroll→hardware preflight→plan topology→review→approve→install→verify S3→bind. `dry_run` mặc định; pin edition/version; chưa chạy tự động trên host thật không có chuẩn cấp phép và runbook.
**Nghiệm thu:** triển khai được cluster test/VM hoặc kết nối cluster đã triển khai; rollback/compensate ở bước phù hợp; không sửa/format disk không được phê duyệt; lỗi giữa chừng không báo ACTIVE.

### S7 — Maintenance & scale lifecycle
**Việc làm:** replace failed host, maintenance preflight (quorum), add server pool, decommission **pool** có đủ capacity; operation plan/version và approval. Phân biệt metadata-only node removal và cluster data operation.
**Nghiệm thu:** reject đổi IP làm mất kết nối, reject xóa active node bằng CRUD; simulate 2 concurrent requests và losing quorum; long job resume; không xóa dữ liệu trước khi xác minh replication/backup/retention.

### S8 — Production readiness & rollout
**Việc làm:** TLS/mTLS, secret rotation, backup DB/config/object/keys, staging→canary organization→wave rollout; observability, dashboards, runbooks, restore drill; SLO/incident response.
**Nghiệm thu:** fault injection, checksum, RPO/RTO được đo; 0 tenant crossover, 0 destructive operations ngoài phê duyệt, 0 data loss trong fixture; có fallback legacy storage và rollback trong triển khai.

## 3. Release strategy
- `storage_control_center_enabled=false` theo mặc định; `storage_multi_cluster_routing_enabled=false` riêng; `storage_agent_operations_enabled=false`; `storage_destructive_operations_enabled=false` luôn bị cấm cho đến S7.
- Migrate schema theo expand→dual-read→backfill→switch→contract; giữ `StorageConfig` và `StorageLocation.provider_version_id` để đọc dữ liệu lịch sử.
- Chuyển từng Organization thử nghiệm bằng binding mới; không đổi cluster cho UploadSession đang tiến hành. Bảo vệ FileVersion referential integrity.
- Đưa UI read-only trước; thao tác hạ tầng phải bật qua action policy, không chỉ feature flag của frontend.

## 4. KPI ban đầu (mục tiêu đo, KHÔNG phải thực trạng)
- Node list/topology API p95 < 300ms @50 nodes, không tính truy vấn telemetry history; test trên staging chuẩn.
- SSE status visible < 5s sau khi backend ghi nhận thay đổi; phụ thuộc chu kỳ scrape (15s/30s) nên **không** cam kết < 5s từ sự kiện vật lý đến UI nếu scrape chậm.
- Agent heartbeat 10–15s; stale sau 3 chu kỳ bỏ lỡ (ngưỡng cấu hình). Khi mất telemetry: UNKNOWN.
- 0 lỗi tenant isolation trong test API/agent; 0 false success khi provisioning fail; no orphan fixtures sau cleanup.
- Canvas 50 nodes: thao tác pan/zoom/selection không giật thấy rõ trên máy tham chiếu, xác nhận bằng trace.

## 5. No-go và trade-offs
- Không tự động triển khai cluster prod bằng MinIO Community archived mà chưa rà license, security maintenance và contract; xác định cụ thể distribution/version với chủ sở hữu pháp lý/kỹ thuật.
- Không mở arbitrary SSH, không lưu mật khẩu root hoặc MinIO admin trong DB plaintext.
- Không dùng mỗi IP address làm định danh node; dùng UUID/agent identity.
- Không giả lập 4 node trên 1 host thành HA production. Demo có thể là single-node hoặc multi-VM, gắn nhãn LAB.
- Không coi server pool expansion là thao tác 'Add Node' đơn lẻ.
