# BlueDrive Storage Control Center — S3 topology

Ngày: 09/11/2026. Nhánh: `feature/storage-control-center-s3-20261109`.

## Kết quả

Đã triển khai phần mã S3: topology canvas và layout preference dùng chung cho Platform/Organization, List view, inspector và lưu bố cục có kiểm soát xung đột. **Backend541 bài:532 PASS,9 MinIO integration SKIP. Chrome72 bài PASS;5 bài Node model PASS; TypeScript/lint/build PASS.**

Cờ `SECUREDRIVE_STORAGE_TOPOLOGY_ENABLED` mới mặc định OFF; `.env` không đổi. Không thêm migration, không backfill dữ liệu, không cài/chạy MinIO, không đổi binding/quota, không vận hành node/pool/agent. G2 MinIO LAB thật vẫn mở; S3 ở trạng thái code đã kiểm chứng, chưa được coi là nghiệm thu vận hành toàn hệ thống.

Giống bản đồ kho: kéo một ô trên sơ đồ chỉ thay cách trình bày; không phải lệnh chuyển kệ hoặc hàng hóa thật.

## Phạm vi và quyết định

Yêu cầu tiếp tục được thực hiện ở phần UI/metadata an toàn. Hướng dẫn gốc `09_CODEX_PROMPTS.md` yêu cầu dừng **thao tác hạ tầng** khi thiếu edition/license/disks/credentials thật và chỉ hoàn thành phần an toàn. Không diễn giải yêu cầu tiếp tục thành phê duyệt license hay vận hành instance đang có dữ liệu.

Dùng `ponytail`, `impeccable` và workflow skill đi kèm roadmap. Giữ token, Button, Dialog và AdminSegmentTabs của BlueDrive. Kiểm tra package upstream/npm và package đã cài: `@xyflow/react`12.12.1, MIT, React peer>=17; pin chính xác version và integrity trong lockfile. Không thêm engine layout khác vì pool/node hiện tại chỉ cần grid xác định. Attribution React Flow được giữ nguyên.

## Thay đổi và lý do

| Nhóm source | Nội dung | Lý do |
|---|---|---|
| `StorageManager`, route Platform và Organization | Một manager dùng lại selector/Connections S2, topology là mục đầu khi có cờ | Hai scope có cùng hành vi và thiết kế, không tạo UI riêng lệch nhau |
| `StorageTopology`, `TopologyCanvas`, CSS module | Pool groups, membership edges, pan/zoom/fit/mini-map, tìm/lọc, auto layout, chuột/touch và dịch vị trí bằng bàn phím | Xem inventory và sắp xếp bản đồ; không nhận lệnh quản lý vật lý |
| `topology-model.ts`, tests | Grid cân đối theo số node, vị trí relative, serialize x/y và filter |100 node không xếp thành dải quá dài; không trộn pool/hostname vào payload save |
| `StorageNodeInspector` | Overview/disks/events scoped, hủy response cũ; panel desktop/native Dialog màn hình nhỏ | Có phản hồi ngay từ snapshot, dữ liệu lỗi được chỉ rõ thay vì giả số liệu |
| `infrastructure/api.py`, URLs, tests | PATCH layout, revision riêng, same-content no-op, expected revision conflict, shared audit; filter disks/events theo node | Chống ghi đè từ cửa sổ cũ và chặn selector vượt cluster/tenant |
| Settings và env example | Cờ topology độc lập, default false, capability rõ | Không mở UI/write preference vô tình khi chỉ triển khai code |
| `Dialog.tsx` | Close và trả focus khi unmount | Sửa lỗi Escape ở mobile inspector, áp dụng cùng cơ chế cho các dialog đang dùng |
| `frontend/tsconfig.json` | Bỏ test-results/playwright-report khỏi program roots | Trước đó908/1148 file root là snapshot artifact; sau sửa240 file nguồn thực, không bỏ tests thực |
| E2E, API/data model/ADR/progress/README | Kiểm chứng và đồng bộ contract | Phân biệt source đã làm với rollout/telemetry còn thiếu |

Danh sách file/SHA-256 nằm trong source-changes.json. Không reset/stash/clean/stage/commit thay đổi cũ. Không tạo PR từ toàn bộ dirty tree.

## Quyền và toàn vẹn dữ liệu

Save layout chỉ nhận scope, expected_revision, positions và viewport. Tọa độ finite, giới hạn500 node, node phải ở cluster được phép. Không nhận owner, pool, endpoint, commands hoặc credentials. Layout cá nhân thuộc người đăng nhập; shared default cần explicit configure. Session CSRF và quyền active được kiểm tra lại trong transaction theo thứ tự khóa tenant/user/cluster.

Hai kết nối DB cùng lưu từ revision0: một200, một409, không mất thay đổi đã thắng. Retry cùng nội dung không tăng revision/audit. Shared layout không ghi đè preference cá nhân. Topology revision, node membership và layout revision độc lập. GET không tạo layout hoặc gọi storage.

Drag/pan không tự gửi request ghi. Layout chưa lưu chặn đổi kho/section và có Discard xác nhận; lỗi save giữ tọa độ hiện tại. Discard trả về bản lưu gần nhất trong phiên, không quay về dữ liệu cũ trước lần Save vừa thành công. Node/pool deletion, connect/reconnect edges và thao tác physical planning không có trong canvas này.

## Kiểm chứng

| Kiểm tra | Kết quả |
|---|---|
| Acceptance trước API layout | FAIL404 như dự kiến; lưu riêng log trước sửa |
| Layout/inventory scoped suite | PASS, gồm race hai DB connection, quyền shared, CSRF, tọa độ sai và selector node khác cluster |
| Full backend discovery |541 bài,532 PASS,9 SKIP; PostgreSQL cluster/DB mới trên loopback, media/email tạm, chặn storage HTTP không mock |
| Node model |5/5 PASS: relative positions, immutable snapshot, deterministic layout, filter và grid100node cân đối |
| Chrome desktop/mobile |72/72 PASS:44 regression cũ,10 S2 và18 S3 |
| TypeScript/ESLint | PASS; phạm vi type-check không còn artifact roots |
| Production build | Next16.3.3 webpack PASS, compile62s, generate39/39; snapshot riêng |
| Django check/makemigrations/migrate check | PASS; không có migration thiếu |

Bộ Chrome cuối chạy trên production snapshot ở cổng riêng, API/S3 đều fixtures intercept. Không dùng saved login hoặc dữ liệu thật. Các lần dev đầu có connection refused do server người dùng chưa chạy và timeout cold compile route404; đã dùng server kiểm thử riêng và chạy lại toàn bộ trên build production. Không sửa sản phẩm để né những lỗi môi trường đó.

Đã thử save/reload, conflict/discard, snapshot lỗi giữ inventory kèm stale, empty không dựng server giả, snapshot quá lớn chuyển list phân trang, node inspector/disk đúng scope, focus Escape, drag chuột và CDP touch mô phỏng. Dark320px không overflow; viewport720px tương đương chiều rộng nội dung desktop khi zoom200% cũng đạt. Đây không phải xác minh thao tác zoom native hoặc thiết bị điện thoại vật lý.

Đã xem screenshot desktop/mobile/dark, thu gọn selector/filter để map xuất hiện sớm hơn, sửa grid100node thành bố cục cân đối. Canvas lazy load trong client boundary, nodeTypes/custom nodes ổn định, có virtual rendering; API không fetch riêng từng node khi render map.

## Benchmark100 node

Fixture100 node, inspector hiển thị từ snapshot trước khi tải details. Bài đo ghi inspector latency và45 rAF intervals khi wheel pan, cùng mean/p95/max; số request storage bị chặn dưới12, không tăng theo từng node.

Giới hạn kiểm tra là inspector<250ms và p95 frame<100ms. Các số đo cụ thể ở benchmark.json; cần xem cả max frame, không suy p95 thành chứng nhận60FPS. Dữ liệu đo là Chrome local với inventory mock, không phải thông số host thật hoặc bảo đảm trên mọi thiết bị.

<!-- S3_BENCHMARK -->

| Project | Inspector ms | Frame mean ms | Frame p95 ms | Frame max ms |
|---|---:|---:|---:|---:|
| desktop | 18.4 | 16.7 | 16.8 | 17 |
| mobile | 67.8 | 16.7 | 16.8 | 16.8 |

Các giá trị này chỉ mô tả lượt đo local, không là bảo đảm60FPS hoặc hiệu năng trên thiết bị khác.

<!-- /S3_BENCHMARK -->

## Vận hành và phần còn lại

Để review UI trong môi trường được phép, cần control center và topology flag; các cờ routing/LAB/agent/destructive vẫn độc lập. Lượt này không bật cờ trên `.env`. Không thể suy Healthy/Offline, CPU/RAM/uptime từ record; hiện Unknown/not_collected. Capacity ghi rõ inventory. Operations/metrics/management chưa được đưa thành hành động vận hành giả trên canvas.

Root type-check đã bỏ908 artifact roots. Với production snapshot, tập file compile hiệu lực trước/sau thay đổi exclude giống hệt nhau, đã kiểm tra bằng TypeScript API; không thay nội dung build ứng dụng. Warning lockfile/workspace root trong snapshot và Node module-type warning của bài strip-types vẫn còn, không làm fail kiểm tra.

Server kiểm thử riêng được quản lý theo PID/session của lượt này; không dừng/restart server người dùng. Báo cáo/evidence xuất Downloads theo allowlist, không chép `.env`, auth/session, license key, secret hoặc DB backup.

G2 vẫn cần một MinIO LAB thật được duyệt edition/license/identity/policy và nghiệm thu luồng S2 thực. Owner review/runtime gate S3 còn mở. S4 monitoring/SSE, S5 agent, S6 provisioning, S7 maintenance và S8 production/restore chưa triển khai. Không có cơ sở để coi toàn bộ roadmap đã hoàn tất.

ADR chi tiết: `ADR-0004-topology-layout-preferences.md`. Workflow inventory → scoped preference API → test concurrency → canvas/list → production browser QA có thể bổ sung vào skill hiện có để tái sử dụng.
