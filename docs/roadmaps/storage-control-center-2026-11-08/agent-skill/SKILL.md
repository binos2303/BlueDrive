---
name: bluedrive-storage-control-center
version: 0.1.0
purpose: Triển khai và rà soát BlueDrive Storage Control Center theo chuỗi gate an toàn, có source evidence và regression.
---
# BlueDrive Storage Control Center — reusable implementation skill

## Trigger
Khi người dùng yêu cầu mở rộng các module MinIO/Storage Manager/React Flow topology/Enterprise Agent/Organization Storage hoặc QA cho những hạng mục đó.

## Workflow
1. Đọc `01_MASTER_PLAN.md`, `02_ARCHITECTURE_SOURCE_MAP.md` và source hiện tại. Không coi tài liệu này là bằng chứng source mới nhất.
2. Xác nhận task thuộc sprint S0–S8, hoàn tất gate trước khi thay đổi.
3. Kiểm kê file/symbol đang có; tránh tạo module mới nếu có service dùng chung. Giữ KISS, DRY, domain cohesion; comment mới bằng tiếng Việt giải thích nghiệp vụ.
4. Viết test fail/acceptance trước cho race/security/data; không làm suy giảm quyền tenant.
5. Thực hiện thay đổi tối thiểu và idempotent; không hoạt động destructive trên MinIO thật nếu chưa có test environment + approval.
6. Chạy test khả dụng, lint, TS build, backend checks và browser tests phạm vi thay đổi.
7. Báo cáo chính xác tests, failures, affected files, migration, observed vs assumed, risk, rollback, next gate. Xuất log về `$env:USERPROFILE\Downloads` trên Windows.

## Must NOT
- Không tự tạo/suspend organization cho user; Platform-only provisioning.
- Không để Platform Admin mặc nhiên đọc dữ liệu Organization hoặc giữ MinIO root keys.
- Không dùng kéo thả UI làm thay đổi topology physical tức thì.
- Không giả trạng thái node `Healthy` khi collector chưa có evidence.
- Không tự thêm node vào MinIO pool đang chạy hoặc xóa active node bằng CRUD.
- Không dùng script format/delete drive, không tự bật phiên bản MinIO chưa chốt licensing.
- Không đổi `StorageConfig` mà bỏ migration/legacy compatibility.

## Definition of Done
Feature có source trace, RBAC, test isolated, evidence logs, migration/rollback, UI states accessibility và được chủ sở hữu xác nhận theo gate.
