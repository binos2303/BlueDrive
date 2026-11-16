# BlueDrive — Chuyển sang quản lý dung lượng bằng gói

Ngày: 08/11/2026.

## Kết quả

Đã bỏ Custom quota trong quản trị nền tảng. Luồng hiện tại là tạo gói → chọn gói hoạt động cho Personal Drive hoặc Workspace cá nhân. Tổ chức không còn xuất hiện trong inventory và lịch sử cấp quota của bảng quản trị này; quản trị tổ chức vẫn tự phân bổ trong phạm vi tenant của họ.

Giống cấp dịch vụ theo bảng gói: định nghĩa các mức dung lượng ở một nơi, sau đó chọn gói cho từng nơi sử dụng. Không nhập lại một hạn mức riêng trên mỗi tài khoản.

## Giao diện đã sửa và lý do

- Trang Storage & Quotas mở mặc định ở Plans & Policies để ưu tiên tạo/quản lý gói.
- Tab Workspace đổi thành Personal workspaces; tìm kiếm không còn gợi ý tìm quota tổ chức.
- Hộp thoại Assign storage plan chỉ có chọn gói và lý do. Xóa lựa chọn Custom quota cùng ô nhập hạn mức riêng; nút Assign plan bị khóa khi chưa có gói hợp lệ.
- Chỉ đưa gói hoạt động, đúng loại Personal Drive hoặc Personal workspace vào danh sách chọn.
- Lỗi tải gói, đang tải và chưa có gói là các trạng thái riêng; có Refresh plans khi lỗi và đường Manage plans để tới danh mục gói.
- Giữ tên của gói đã ngừng hoạt động khi hiển thị phân bổ cũ. Tài khoản chưa có gói hiển thị Not assigned thay cho Custom; không tự thay hạn mức.
- Cập nhật các ca browser kiểm tra modal, lỗi lưu và chặn Escape khi request đang chạy theo nhãn mới.

## API và quyền

`PATCH /accounts/api/admin/quotas/{quota_id}/` chỉ nhận:

```json
{"plan_code":"free","reason":"Assign a defined storage package"}
```

Server từ chối hạn mức tùy ý, cả trường hợp gửi kèm `limit_bytes: null`, gói rỗng, gói không tồn tại, gói inactive hoặc sai scope. Quyền Super Admin và CSRF vẫn được kiểm tra.

Trong transaction, quota account và gói được khóa; hạn mức lấy từ gói tại server. Không nhận giá trị hạn mức do client gửi và không reset `used_bytes`/`reserved_bytes`. Gán lại cùng gói và cùng hạn mức là no-op, không tạo audit trùng.

Inventory Workspace, số lượng kết quả tìm kiếm và lịch sử thay đổi quota của nền tảng chỉ lấy tenant cá nhân. API nền tảng tiếp tục từ chối sửa quota business bằng ID trực tiếp. Lịch sử tổ chức không bị xóa; API tự quản trị tổ chức vẫn kiểm tra owner/admin và tenant của chính họ.

## Dữ liệu cũ và phạm vi

Không migration hay sửa quota thật hàng loạt. Các phân bổ cũ giữ nguyên hạn mức cho đến khi có thao tác chọn gói. Đổi định nghĩa gói không tự đổi các phân bổ đã cấp, theo cơ chế snapshot hiện có; chọn lại gói sẽ áp dụng định nghĩa hiện tại. Đổi gói không xóa file; kiểm tra quota khi upload vẫn hoạt động.

Tài khoản cá nhân của một thành viên tổ chức vẫn là Personal Drive riêng. Việc loại quota tổ chức dựa trên `Tenant.kind=business`, không loại nhầm Drive cá nhân của người đang tham gia tổ chức.

Không triển khai billing, thanh toán hoặc tự chuyển mọi quota cũ sang một gói suy đoán. Không đổi cấu hình storage, worker, bucket hoặc cách tổ chức tự triển khai hệ thống riêng.

## Kiểm chứng

| Nhóm | Kết quả |
|---|---|
| Backend chọn lọc về plan/quota/provisioning/upload | 41/41 đạt |
| Toàn bộ backend | 442 ca: **433 đạt, 9 MinIO integration bỏ qua**, không lỗi |
| Chrome desktop/mobile, API giả lập | **18/18 đạt** |
| TypeScript | Đạt |
| ESLint các file frontend thay đổi | Đạt |
| Diff whitespace check | Đạt |

Đã xem ảnh gán gói và tạo gói trên desktop 1440×900, mobile mô phỏng 390×844. Các ca browser còn kiểm tra thiếu gói, lỗi tải/phục hồi, đúng scope, gói inactive, dữ liệu chưa gán gói, lỗi lưu trong modal và khóa đóng khi đang lưu.

Backend dùng PostgreSQL test riêng, media tạm, email trong bộ nhớ; chặn HTTP storage chưa mock, dùng hasher nhanh chỉ trong tiến trình test và hủy database test sau chạy. Không chạy 9 ca MinIO thật vì cần bucket thử riêng. Browser không thao tác lên tài khoản/gói thật. Các nhóm test có phần trùng nhau, không cộng thành tổng số test độc lập.

Bằng chứng trong workspace:

- `frontend/test-results/roadmap-repairs/plans-before.txt`: tái hiện các hành vi cũ không đáp ứng hợp đồng mới.
- `frontend/test-results/roadmap-repairs/plans-backend.txt`: 41 test chọn lọc đạt.
- `frontend/test-results/roadmap-repairs/plans-full-backend.txt`: toàn bộ backend đạt, 9 skip.
- `frontend/test-results/plans-ui-final/`: 12 ca browser đầu và ảnh giao diện.
- `frontend/test-results/plans-ui-edge/`: 6 ca bổ sung về lỗi tải/scope/dữ liệu cũ.

## File chính

`backend/accounts/quota_admin_api.py`, `backend/accounts/test_quota_management.py`, `frontend/components/admin/QuotaManagement.tsx`, `frontend/components/admin/QuotaPlanPolicies.tsx`, `frontend/e2e/storage-plans.spec.ts`, `frontend/e2e/mocked.spec.ts`, `frontend/e2e/admin.spec.ts`, `docs/API_CONTRACT_V1.md`.

Skill sử dụng: ponytail cho thay đổi chung ở API và tái sử dụng mô hình gói; impeccable phần harden/clarify cho chọn gói, trạng thái lỗi và kiểm tra giao diện.
