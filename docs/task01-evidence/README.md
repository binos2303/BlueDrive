# Bằng chứng Task 01

Xem kết luận trong [báo cáo](../BLUEDRIVE_SEAWEEDFS_TASK01.md). Các log không chứa secret/config private. File log được chuẩn hóa UTF-8 trước bàn giao. HTTP 400/403/409 và các log finalizer xuất hiện trong regression có thể là tình huống âm được test có chủ đích; đọc kết quả tổng cuối log.

- `git-status-before.txt`: snapshot working tree ban đầu, không dùng làm patch để reset.
- `baseline-frontend-{lint,typecheck,tests}.log`: PASS; Node có 159 bài.
- `baseline-frontend-build.log`: lỗi mạng Google Fonts; `baseline-frontend-build-network.log`: PASS sau chạy có mạng.
- `baseline-django-check*.log`, `baseline-migrations*.log`, `baseline-backend-tests*.log`: quá trình xác định cấu hình process DEBUG và lỗi discovery 0 test; không coi các lượt không chạy bài test là PASS.
- `initial-backend-regression.log`: 567 bài, fail một expectation cũ về public signer; đã sửa test contract và xác minh adapter sau đó.
- `final-targeted-regression.log`: test DB tái dùng thiếu Storage Plan seed sau flush; runner mới dùng database test cách ly.
- `final-django-check.log`, `final-migrations.log`: PASS.
- `final-adapter-tests.log`: 33 bài PASS, mock/unit; không chứng nhận SeaweedFS.
- `shared-zip-regression.log`: 2 bài PASS (S3 mock, AES/ZIP thật).
- `final-sharing-regression.log`: 61 bài PASS trên DB riêng.
- `final-backend-regression.log`: 571 bài trên database riêng, 552 pass, 19 skip, 0 lỗi. Sau sửa ZIP cuối đã chạy lại toàn bộ 61 bài sharing.
- `configure-tests.log`: 2 bài PASS.
- `compose-static-check.txt`: YAML/static topology PASS; không phải Docker config/runtime PASS.
- `real-storage-gate.log`: BLOCKED, setUpClass không kết nối được SeaweedFS, 0 bài chạy; không coi là bằng chứng tương thích.
- `cutover-inventory.json`: kiểm kê aggregate chỉ đọc, không cấp phép xóa.

Không có Docker runtime hoặc native SeaweedFS thành công trong phiên này. Browser/restart/worker thật vẫn BLOCKED; runbook có lệnh chạy tiếp sau khi môi trường sẵn sàng.
