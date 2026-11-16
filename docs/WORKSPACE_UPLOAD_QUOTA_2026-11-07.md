# Kiểm tra upload Workspace và quota — 07/11/2026

## Kết quả

Đã tìm và sửa một lỗi CORS thực tế: backend thiếu `x-workspace-id` trong `CORS_ALLOW_HEADERS`. Chrome chặn preflight của các request chọn Workspace, gây lỗi tải Drive/quota và không khởi tạo được upload. API gọi trực tiếp vẫn hoạt động nên bộ test dùng APIClient hoặc mock frontend trước đó không chứng minh được trường hợp này.

Sửa tại `backend/securedrive/settings.py`: thêm đúng header Workspace vào danh sách hiện có. Không đổi allowed origins, credentials, CSRF, quyền Workspace hoặc cách tính quota. Test origin không được tin cậy vẫn không nhận `Access-Control-Allow-Origin`.

Regression trước sửa thất bại trên ba endpoint `/drive/api/items/`, `/accounts/api/me/quota/`, `/files/api/uploads/`; sau sửa đạt. Preflight trên server đang chạy cũng trả header được phép. Chrome sau đó thực hiện được luồng thật.

## Luồng thật đã xác minh

Chrome + frontend `http://localhost:3000`, Django `http://localhost:8000`, session tài khoản thử thường. Tạo một Workspace thử mới với gói mặc định 100 MiB. Không sửa quota hoặc thành viên của Workspace có sẵn.

| Bước | Workspace used | Workspace reserved | My Drive used/reserved |
|---|---:|---:|---:|
| Workspace mới | 0 | 0 | 0 / 0 |
| Hai yêu cầu đồng thời, mỗi yêu cầu giữ 50 MiB + 1 byte | 0 | 52,428,801 bytes | 0 / 0 |
| Hủy phiên được nhận | 0 | 0 | 0 / 0 |
| Upload thật 9 MiB hoàn tất | 9,437,184 bytes | 0 | 0 / 0 |
| Dọn file thử | 0 | 0 | 0 / 0 |

- Hai yêu cầu admission đồng thời trả **201 và 413**: chỉ một phiên giữ chỗ; phiên kia có `failure_code=quota_exceeded`. Đây là kiểm tra metadata/reservation, không truyền hai file 50 MiB lên storage.
- Abort phiên đã nhận trả 200/canceled và hoàn trả toàn bộ reserved. Quota cá nhân giữ nguyên gói 10 MiB trong mọi snapshot.
- Qua UI **New → Upload files**, file 9 MiB được chia thành hai part 8 MiB + 1 MiB, finalize và chuyển thành Available. Các request control plane của browser giữ đúng Workspace ID.
- File xuất hiện trong Workspace, không xuất hiện trong My Drive. Download qua Django khớp từng byte với dữ liệu tạo bởi ca kiểm thử. Sidebar hiển thị 9% của 100 MiB sau hoàn tất.
- Chỉ file thử vừa tạo và đã đối chiếu nội dung được trash/delete. Quota trở về 0; Workspace thử được archive qua API. Lượt browser thất bại trước sửa không tạo file, reserved đã về 0 và Workspace rỗng đó cũng đã được archive. Metadata/audit lịch sử được giữ lại theo cơ chế ứng dụng.

Lượt chốt desktop: **1 scenario đạt trong 21.1 giây**, không skip/retry/flaky. Đã xem ảnh kết quả. Báo cáo riêng: `frontend/playwright-report/workspace-upload/index.html`; JSON/snapshots ở `frontend/test-results/workspace-upload-results.json`. Không ghi cookie, CSRF token, provider upload ID hoặc URL ký vào bằng chứng. Các artifact này được Git bỏ qua.

## Kiểm tra hồi quy

- **54 backend tests đạt** trong một lượt sau sửa, trên PostgreSQL test DB có UUID riêng, media tạm và email locmem. Database ứng dụng không bị thay thế; test DB được runner dọn sau kiểm tra.
- Bao gồm **10 ca mới** với quota thật và storage mock: Editor ở tenant khác chỉ giữ quota Workspace; replay idempotency; vượt quota; abort lặp; lỗi khởi tạo storage; quota thiếu; Viewer không thể upload; Editor bị hạ role không thể authorize/complete nhưng có thể abort; session hết hạn; finalize thành công và thất bại.
- Có kiểm tra đồng thời bằng row locks PostgreSQL, quota Workspace/My Drive độc lập, cấp quota sai scope bị chặn, publication/checksum và luồng quản trị quota sẵn có.
- **2 CORS tests mới**: preflight của ba endpoint Workspace và từ chối origin lạ.
- **31 frontend unit tests đạt**: chụp đích upload trước khi đổi Workspace, request scope, task state/retry/pause/cancel, part authorization và receipt reconciliation.
- TypeScript, ESLint cho ca browser mới và diff whitespace check đạt.

## Chạy lại

Giữ frontend, backend và `run_upload_finalizer` đang chạy. Đăng nhập tài khoản thử thường trước khi chạy:

```powershell
cd frontend
npm run test:e2e:auth
npm run test:e2e:workspace-upload
```

Ca thật tạo Workspace riêng, kiểm tra admission, upload 9 MiB rồi dọn file và archive Workspace. Guard chỉ chấp nhận quota khởi tạo lớn hơn 9 MiB và không quá 100 MiB để tránh giữ lượng dung lượng quá lớn do cấu hình tùy chỉnh. Không chạy với tài khoản sản xuất hoặc nâng quota hiện có để làm test đạt.

Các test backend liên quan:

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py test files.tests.test_upload_api files.tests.test_quota files.tests.test_workspace_access files.tests.test_finalization_streaming accounts.test_quota_management files.tests.test_workspace_upload_quota accounts.test_workspace_cors
```

Không chạy đồng thời hai runner dùng cùng test DB. Phiên kiểm tra này đã chủ động đặt tên test DB UUID mới để tách biệt.

## Giới hạn bằng chứng

Ca browser thật chạy bằng chủ Workspace/Admin của Workspace mới. Editor/Viewer, folder đích, role downgrade, expiry và các lỗi storage được kiểm tra trên DB test với storage mock; chưa chạy lại các tình huống đó trên MinIO thật bằng tài khoản thứ hai. Không khẳng định đây là load test, thử mạng chập chờn đầy đủ hoặc nghiệm thu toàn bộ ứng dụng.

Có thể đóng gói quy trình kiểm tra preflight → DB test riêng → race quota → Chrome multipart → đối chiếu download → dọn fixture thành Agent Skill dùng lại.
