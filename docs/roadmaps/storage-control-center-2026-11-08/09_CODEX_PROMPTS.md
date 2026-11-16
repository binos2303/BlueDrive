# 09 — Copy-ready Codex prompts, triển khai tuần tự

**Không chạy cùng lúc các sprint.** Đọc `01_MASTER_PLAN.md` trước; mỗi sprint tạo branch/PR riêng, tự chạy regression khả dụng, báo cáo bằng chứng. Không được hỏi người dùng câu hỏi đã được đặc tả trong bộ này, nhưng khi thiếu edition/license/disks/credentials thật thì phải **dừng thao tác hạ tầng**, chỉ hoàn thành phần an toàn.

## Prompt 0 — Repository audit và baseline (read-only)
> Kiểm toán source BlueDrive trên máy hiện tại, không thay source production. Truy vết `StorageConfig`, `StorageLocation`, `UploadSession`, `get_storage_adapter()`, Organization quota API, Platform Admin, Organization Admin UI, topology placeholder. Xác minh giả định trong 02_ARCHITECTURE_SOURCE_MAP.md; lập call graph, test matrix, danh sách các route/model hiện hữu và các feature flags. Dò secret trong bản export nhưng không in giá trị. Chạy tests hiện có trên DB test riêng, ghi log về `%USERPROFILE%\\Downloads\\BLUEDRIVE_SCC_S0`. Trả báo cáo findings với file:line + điều chưa biết. Không tự triển khai MinIO.

## Prompt 1 — Inventory domain + RBAC
> Triển khai S1 theo master plan. Tái sử dụng `Tenant`, `Membership`, `StorageConfig`, Organization quota. Tạo schema tối thiểu cho StorageCluster/Node/Pool/Layout/OperationJob và policy quyền tenant scoped; migration backward compatible. Không xóa unique constraint `StorageConfig(tenant,provider)` ở MVP; chưa bật multi-cluster routing. API GET phải check scoped tenant, 404 cho cross-tenant. Tests: permissions, uniqueness, concurrent creates, migration, Django checks. Không đổi upload/download existing. Viết comment tiếng Việt giải thích business invariants. Xuất diff, tests, risk log trong Downloads.

## Prompt 2 — Connect Existing Cluster read-only
> Triển khai S2: connect-existing draft + verify MinIO/S3 với allowlisted endpoints, TLS validation, credential_ref external secret; không trả secret client. Dùng storage adapter hiện có, không rewrite boto3. S3 fixture phải nằm trong bucket test do tool tạo và cleanup đúng fixture. Không có arbitrary SSRF; chỉ auto-activate cluster sau mọi validation. Test negative credential/TLS/unreachable/cross-tenant. Giữ feature flag OFF mặc định. Không tác động MinIO production.

## Prompt 3 — Interactive React Flow Canvas
> Triển khai S3 trong route topology admin hiện hữu và organization storage route, dùng một component `StorageManager`. Thêm `@xyflow/react` version phù hợp và kiểm tra license/version. Canvas có grouped pool/node, drag position only, pan/zoom/mini-map, click inspector, auto layout, search, offline/unknown/status source, List View keyboard. Layout lưu riêng topology, không API mutation từ drag. Reuse BlueDrive colors/components/layout; không tạo UI rời rạc. Tests unit, Playwright responsive/keyboard, build/lint. Mock data chỉ trong test/story; runtime không gắn nhãn LIVE cho mock.

## Prompt 4 — Monitoring thật
> Triển khai S4 MinIO metrics theo edition/version và host agent/node_exporter read-only; separation snapshot vs timeseries, freshness timestamps, status UNKNOWN khi mất telemetry, cluster health từ quorum endpoints. Cung cấp scoped REST+SSE, resync/reconnect, alerts + audit. Không poll backend theo từng node mỗi lần client re-render. Tests source completeness, stale/offline distinction, cross-tenant, update concurrency, browser live fixtures. Không gửi secret/URLs vào telemetry.

## Prompt 5 — Agent enrollment
> Thiết kế và triển khai S5 agent prototype chạy trên VM dev: outbound mTLS, one-time enrollment, signed allowlisted read-only jobs, identity rotate/revoke, no arbitrary shell/SSH. Dùng OS user ít quyền, secure logs. Negative tests tenant tamper, replay, expiry, wrong cert, disconnect, duplicate delivery. Không bật install/start/stop service chưa được phê duyệt.

## Prompt 6 — Provisioning LAB only
> Sau G4, triển khai S6 wizard draft->preflight->plan->approve->execute->verify->bind dành cho MinIO version/edition được cấu hình rõ. Chỉ hoạt động lab, dry_run default và feature gate. Agent không format disk; chỉ dùng path/drive đã được lab owner cấp phép. Job checkpoints/fencing, fail states, audit. Quorum, erasure constraints, TLS, S3 checksum verified. Nếu edition/license chưa chốt: chỉ làm UI/dry-run và báo BLOCKED, không chạy cài đặt thật.

## Prompt 7 — Operations & final hardening
> Sau S6, triển khai S7/S8 theo runbook: safe maintenance, replace, pool expansion/decommission version-aware. Không tạo nút delete node live thực thi ngay. Testing PostgreSQL concurrency, MinIO fault injection trong isolated cluster, telemetry, backup/restore, retention và canary. Mỗi operation có approval + immutable plan hash. Triển khai tuần tự; chạy tests và báo cáo có bằng chứng, không tự làm thay đổi production.

## Format kết quả Codex bắt buộc
1. Đã kiểm tra source và exact files/lines.
2. Changed files và lý do từng thay đổi.
3. Tests run + PASS/FAIL/SKIPPED, log path trong Downloads.
4. Cập nhật migration/API contract và compatibility.
5. Các rủi ro chưa giải quyết; rollback procedure.
6. Gate tiếp theo đã đủ điều kiện hay bị BLOCKED.
