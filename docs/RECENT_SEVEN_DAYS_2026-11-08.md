# Recent — Chỉ hiện file hoạt động trong 7 ngày

Ngày: 08/11/2026.

## Thay đổi

- Recent cá nhân và Workspace chỉ hiện file có hoạt động trong 7 × 24 giờ tính lùi từ hiện tại, kể cả đúng mốc bắt đầu.
- Hoạt động lấy thời điểm mới nhất giữa `updated_at` và `last_accessed_at`: chỉnh sửa/tải lên hoặc mở/tải file theo cơ chế ghi nhận hiện có.
- Không hiện folder, file trong Trash, file có tổ tiên đã xóa hoặc file ngoài quyền/Workspace hiện hành. Timestamp ở tương lai bị loại.
- File cũ được mở lại sẽ trở lại Recent. Không xóa dữ liệu; My Drive vẫn giữ các file cũ.
- Tìm kiếm trong Recent cũng giữ giới hạn 7 ngày. Sắp xếp hoạt động mới nhất trước, giữ giới hạn tối đa 100 kết quả hiện hành.
- Empty state nói rõ khoảng 7 ngày.

## Vì sao tách truy vấn biểu đồ

Biểu đồ trong Workspace Activity log trước đây gọi cùng `view=recent`. Nếu chỉ thêm cutoff, biểu đồ 14 ngày sẽ thiếu nửa đầu dữ liệu. Biểu đồ chuyển sang `view=timeline`, giữ dữ liệu file/folder 14 ngày và chỉ cho phép quản lý Workspace truy cập. Endpoint audit-event và thời gian lưu log không đổi; không thêm mục điều hướng cho người dùng.

Giống hai màn hình cùng đọc một sổ: danh sách vừa dùng nhìn 7 ngày, biểu đồ quản lý vẫn nhìn 14 ngày.

## Kiểm chứng

- 38 test backend chọn lọc đạt, gồm 7 test mới cho Recent/timeline, search, listing, direct share và authorization boundaries.
- 4 ca Chrome desktop/mobile với API giả lập đạt: empty state Recent và biểu đồ Activity log.
- Đã xem ảnh desktop/mobile; nội dung hiển thị đầy đủ, không tràn ngang.
- TypeScript, ESLint các file frontend thay đổi và diff whitespace check đạt.
- Backend dùng PostgreSQL test riêng, media tạm, email trong bộ nhớ và storage HTTP chưa mock bị chặn. Database test đã được hủy. Không chạy lại toàn bộ backend hoặc MinIO thật cho thay đổi này.

Bằng chứng: `frontend/test-results/roadmap-repairs/recent-before.txt`, `recent-final.txt`, `frontend/test-results/recent-seven-days-ui/`.

## File sửa

`backend/dashboard/views.py`, `backend/dashboard/test_recent_files.py`, `frontend/components/drive/DriveFileBrowser.tsx`, `frontend/components/workspaces/WorkspaceActivityPage.tsx`, `frontend/lib/drive-service.ts`, `frontend/e2e/mocked.spec.ts`, `docs/API_CONTRACT_V1.md`.
