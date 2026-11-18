---
name: bluedrive-storage-validation
description: Qualify BlueDrive SeaweedFS S3 storage through real provider tests, Tenant isolation, application E2E, persistence, outage recovery, and fixture backup and restore. Use for storage qualification or changes to storage, upload, download, and finalization contracts.
---

# Nghiệm thu storage BlueDrive

Chọn gate theo thay đổi hoặc phạm vi nghiệm thu được yêu cầu. Skill hướng dẫn cách kiểm chứng trên fixture đã được duyệt. Merge, deploy, migrate serving database, cutover, đổi routing/credentials phục vụ và thao tác phá hủy dữ liệu cần quyền riêng.

Đọc [AGENTS.md](../../../AGENTS.md), phần infrastructure trong [MAP.md](../../../MAP.md) và [runbook SeaweedFS](../../../infra/seaweedfs/README.md) trước khi chạy. Dùng [hướng dẫn E2E](../../../frontend/e2e/README.md) cho bài browser, [Enterprise Lab runbook](../../../infra/enterprise-lab/README.md) cho cấu hình Enterprise và [báo cáo qualification](../../../docs/PLATFORM_QUALIFICATION_2026-11-13.md) cho bằng chứng P4 theo từng lần chạy.

## 1. Preflight

- Ghi commit SHA, trạng thái working tree, môi trường và phiên bản/digest thực tế. Xác định mỗi đích là Platform hay Enterprise, đồng thời là serving hay fixture.
- Đối chiếu Compose project với container IDs/labels, network, mount và volume ownership. Xác minh S3 endpoint, public signer/origin, bucket/key namespace, storage identity, database host/port/name/role và marker nếu runner yêu cầu. Kiểm tra lại ownership trước khi restart, restore hoặc cleanup.
- Cô lập mọi đường ghi khỏi serving. Dùng DB, volume, network, bucket, identity, tài khoản và cấu hình fixture riêng. PostgreSQL ứng dụng giữ nghiệp vụ/quyền/quota/audit. Mỗi Filer dùng database và role riêng cho `filemeta`. Giữ settings/env, media và email của test cô lập. Chỉ chạy config generator trong thư mục fixture.
- Thiếu bằng chứng ownership, isolation hoặc quyền ghi thì đánh dấu gate phụ thuộc **BLOCKED** và tiếp tục các kiểm tra độc lập chỉ đọc. Xét cả tác động do Docker Engine tự khởi động lại container khi cần bật Engine. Bảo vệ cấu hình và evidence riêng, chỉ xuất thông tin đã che dữ liệu nhạy cảm.

## 2. Provider Qualification

- Chạy regression adapter/config liên quan và dùng live runner theo runbook. Kiểm tra Master/Volume/Filer/S3, Volume đăng ký với Master và Filer kết nối PostgreSQL đúng role. Signed requests phải thực thi thành công để xác nhận readiness.
- Bootstrap đúng bucket fixture còn thiếu bằng operator identity đã duyệt. Dùng application identity giới hạn bucket cho data-plane tests, gồm cả kiểm tra từ chối. Giữ nguyên CORS, versioning và policy của bucket hiện hữu. Tránh gọi bucket administration để thử denial.
- Kiểm PUT, GET, HEAD, DELETE, Range GET và metadata. Kiểm multipart qua part receipts/ListParts, resume cùng upload, complete lặp và abort. Xác minh SHA-256 toàn file, part checksum, composite semantics, conditional copy và read/delete theo VersionId. Dùng ETag hoặc composite checksum theo đúng ý nghĩa của provider.
- Kiểm presigned URLs hợp lệ, sai và hết hạn. Chạy Chrome CORS thật đúng origin và host đã ký, giữ nguyên URL và kiểm required headers cùng ETag/checksum đọc được. Kiểm anonymous, sai identity và cross-bucket denial trên S3, cùng cross-Tenant denial tại Django.
- Chạy upload API → S3 → finalizer thật → download trên PostgreSQL fixture. Kiểm file rỗng, hash sai, replay idempotent, quota reservation/consumed/released và audit. Full qualification cần kết quả live thực thi. Mock, unit và provider SKIP được báo riêng.

## 3. Full Application E2E

- Dùng Next.js, Django, PostgreSQL, SeaweedFS và worker thật trên fixture. Qua UI, kiểm login với session/CSRF → My Drive/Workspace → upload → finalization → download → rename → move → share → trash → restore. Dùng desktop/mobile cho luồng hỗ trợ và ghi viewport hay thiết bị đã dùng.
- Quan sát browser PUT parts thật và native GET nguyên URL đã ký, đúng endpoint và VersionId. Đối chiếu bytes/SHA-256 với FileVersion và StorageLocation. Chỉ chấp nhận UI hoàn tất sau trạng thái AVAILABLE do backend xác nhận. Xác minh quyền, quota đúng scope và audit qua API/DB fixture.
- Với Enterprise, dùng Organization, cluster, Storage Connection đã được xác minh và Binding riêng. Kiểm managed My Drive đúng Tenant, binding thiếu/sai Tenant/chưa READY và routing OFF bị từ chối theo contract, upload/download ghim đúng revision. Kiểm chéo Organization, Org Admin với file private employee và membership bị thu hồi. Ghi TTL còn lại của URL đã cấp khi đánh giá việc thu hồi quyền.

## 4. Persistence & Outage Recovery

- Dùng persistent volumes thuộc fixture. Lưu manifest private trước thử nghiệm gồm định danh FileVersion, StorageLocation, object key, VersionId, revision, kích thước, SHA-256, owner/Tenant/Workspace, quota/reservations và audit.
- Gián đoạn có kiểm soát Gateway, Filer và finalizer thuộc fixture đã xác minh. Thử ngắt upload rồi resume, ngắt finalization rồi retry. Sau khi khôi phục và restart đúng services fixture trong phạm vi duyệt, so metadata ứng dụng, Filer `filemeta` và bytes theo pinned version.
- Xác minh file chưa AVAILABLE khi worker chưa xác minh object. Đối chiếu mỗi logical file, current version, reservation và UPLOAD audit sau retry để phát hiện publication trùng hoặc quota tính hai lần. Ghi rõ phần đã kiểm bằng outage thật và phần chỉ kiểm bằng fault injection.

## 5. Backup & Restore

1. Xác minh source là fixture đã duyệt và kiểm kê mọi writer. Drain công việc hoặc ghi rõ trạng thái in-flight cần giữ. Dừng writer ứng dụng và storage của fixture tại cùng consistency point, kể cả khả năng còn ghi từ presigned PUT đã cấp.
2. Sao lưu PostgreSQL ứng dụng, PostgreSQL Filer từng cluster, dữ liệu SeaweedFS cần cho version references và cấu hình/recovery material tương ứng. Ghi timestamp, source SHA, inventory và SHA-256 của từng dump/archive/bundle vào manifest consistency private. Hạn chế quyền truy cập trước khi ghi backup.
3. Kiểm checksum trước restore. Khôi phục vào Compose projects, networks, databases và persistent volumes mới đã xác minh rỗng và độc lập. Giữ nguyên môi trường nguồn. Nếu cần giữ địa chỉ signer để bảo toàn revision, xác minh source fixture đã dừng và chỉ restore fixture nhận traffic.
4. So toàn bộ metadata trong manifest với snapshot và xác minh object versions. Đọc lại qua Django và presigned S3, đối chiếu bytes, SHA-256, size, owner/Tenant/Workspace, quota/reservations và audit. Thử các quyền hợp lệ và cross-Tenant denial trên dữ liệu đã restore. Gate chỉ PASS khi kiểm được cả tính toàn vẹn và quyền truy cập sau import.

## 6. Cleanup & Retention

- Ghi receipt trước thao tác ghi khi có thể, với đích fixture và định danh đủ để đối chiếu. Chỉ cleanup object/version, multipart upload, probe hoặc resource do lần chạy tạo và có ownership cùng quyền xóa đã xác minh. Kiểm lại versions, delete markers và multipart còn sót. Báo lỗi hoặc tài nguyên chưa xác minh được.
- Với volumes hoặc backup private giữ để review, ghi số lượng, chủ sở hữu/người phụ trách, lý do và thời hạn lưu do operator xác nhận. Nếu chưa có thời hạn, ghi đang chờ xác nhận và ghi mốc review nếu đã hẹn. Việc xóa recovery material cần phê duyệt riêng, kể cả sau mốc lưu giữ.

## 7. Acceptance

Ghi từng trạng thái theo bằng chứng tương ứng:

| Trạng thái | Bằng chứng cần có |
| --- | --- |
| PLATFORM FIXTURE QUALIFIED | Provider, connection và giới hạn access của Platform fixture |
| ENTERPRISE FIXTURE QUALIFIED | Provider và Organization/Binding isolation trên Enterprise fixture |
| FULL APPLICATION E2E VERIFIED | Các luồng UI thật, bytes, quyền, quota và audit |
| PERSISTENCE VERIFIED | Metadata và pinned bytes khớp sau restart fixture |
| OUTAGE RECOVERY VERIFIED | Resume/retry qua gián đoạn thực, accounting đúng một lần |
| BACKUP/RESTORE VERIFIED | Restore sang fixture mới, đọc lại đúng versions và kiểm quyền |
| SERVING RUNTIME VERIFIED | Bằng chứng độc lập từ đúng runtime serving trong phạm vi đã duyệt |
| PRODUCTION RELEASE ACCEPTED | Các release gates production đạt và có phê duyệt phát hành |

Fixture PASS chỉ áp dụng cho môi trường đã kiểm. HA, RPO/RTO, TLS/SSE và client-side encryption production cần bằng chứng riêng ở môi trường đại diện.

## 8. Báo cáo

Cập nhật [báo cáo qualification hiện có](../../../docs/PLATFORM_QUALIFICATION_2026-11-13.md) khi chạy gate. Với mỗi gate, ghi SHA, thời điểm, môi trường/phiên bản, lệnh hoặc test, số ca thực thi và **PASS / FAIL / SKIP / BLOCKED**, bằng chứng, giới hạn và disposition tài nguyên. Phân biệt lỗi đã tái hiện, test không thực thi và blocker thiếu điều kiện. Chỉ đưa bằng chứng đã che dữ liệu lên GitHub. Giữ secret, presigned URL, auth state, raw manifests và recovery material trong nơi lưu private.
