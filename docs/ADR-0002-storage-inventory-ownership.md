# ADR-0002 — Ownership và phạm vi inventory Storage Control Center

Ngày: 08/11/2026. Phạm vi: S1, mã nguồn sau khi người dùng cho phép bắt đầu triển khai. Chưa phê duyệt vận hành hạ tầng.

## Vấn đề

Lộ trình yêu cầu Platform sở hữu cluster riêng, Organization sở hữu cluster doanh nghiệp. `Tenant` hiện chỉ có `personal`/`business`; dedicated Platform Admin không có personal tenant. Dùng tenant của một admin sẽ làm ownership phụ thuộc tài khoản đó. Thêm `Tenant.Kind.PLATFORM` ảnh hưởng các constraint, tín hiệu tạo workspace, quota và query hiện hữu.

## Quyết định

`StorageCluster.kind` là owner scope bắt buộc:

- `platform`: chủ quản là Platform, `tenant_id` bắt buộc NULL.
- `enterprise`: chủ quản là Organization, `tenant_id` bắt buộc trỏ Tenant business.

Check constraint chặn tổ hợp thiếu/sai scope. Trigger PostgreSQL chặn enterprise dùng personal tenant và chặn đổi owner sau khi tạo. API suy scope từ route và principal; client không được chọn scope trong body/query. Platform route chỉ lọc kind platform; Organization route chỉ lọc đúng tenant business đang active. Scope Platform cố định không phụ thuộc tài khoản cá nhân.

Đây là điều chỉnh cụ thể so với cột tenant bắt buộc trong bản kế hoạch: cluster Platform dùng namespace chủ quản Platform tường minh thay vì tạo Tenant giả. Cluster doanh nghiệp vẫn có FK tenant bảo vệ. Không tạo Organization model thứ hai.

Giống kho công ty và kho khách hàng: kho công ty đứng tên công ty, không đứng tên cá nhân người quản lý; kho khách hàng phải chỉ rõ khách hàng sở hữu.

## Quyền và bootstrap

`StorageAccessGrant` gắn từng capability với Membership business. Org Owner/Admin/Workspace Admin không mặc nhiên có quyền xem storage. Organization Owner active có API riêng để cấp/thu hồi capability một cách chủ động, có CSRF, expected_permissions và audit. Owner có thể cấp quyền xem cho chính mình trước khi có cluster, không cần Platform Admin hoặc sửa DB thủ công.

Platform Admin chỉ xem inventory Platform; quyền Platform không cho truy cập route Organization, kể cả khi có membership/grant. S1 chưa có support grant chéo tenant. Quyền storage không thay đổi ACL file.

## Dữ liệu và compatibility

`StorageConfig`, `StorageLocation`, UploadSession, factory và data plane không bị thay đổi. Giữ unique tenant/provider của StorageConfig. StorageBinding mới chỉ là metadata; chưa được resolver hiện tại sử dụng. Active binding yêu cầu cluster verified/config active, scope cùng tenant; MVP business chỉ có một cluster active qua mọi binding.

Không backfill cluster từ endpoint/object key suy đoán. Không tự tạo demo cluster hoặc chuyển object. S1 không lưu credential trong inventory hoặc trả credential_ref/raw config ra API.

TopologyLayout lưu preference riêng, có revision độc lập. S1 chỉ đọc layout, không ghi tọa độ hoặc thay topology. OperationJob bị constraint dry_run=True; chưa có handler execute.

## Hệ quả và phần còn lại

S2 phải xác minh connection và xây resolver ghim config cho toàn vòng đời upload, đồng thời dùng StorageLocation cho file cũ. S3 mới thêm React Flow và lưu layout. S4 mới có nguồn telemetry; hiện health luôn Unknown. S5/S6 phải thiết kế danh tính agent, approval và execution riêng; không dùng UUID inventory làm chứng nhận agent.

Schema additive được kiểm tra up/down trong DB thử. Rollback triển khai ưu tiên giữ schema và tắt feature flag. Chỉ drop app schema trên DB thử hoặc khi đã sao lưu và xác nhận có thể bỏ toàn bộ inventory/audit mới; không tự chạy rollback có dữ liệu trên DB ứng dụng.
