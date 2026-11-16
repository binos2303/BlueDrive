# Thực hiện README bộ kiểm chứng A01–A12 — 08/11/2026

## Kết quả hiện tại

Đã đọc đủ 142 dòng của `C:\Users\dang2\Downloads\README.md` và thực hiện những kiểm tra độc lập có thể chạy an toàn. **Chưa thể thực thi bộ kiểm chứng A01–A12 gốc vì chưa có verification kit.** Không sửa application source, cấu hình `.env`, test nghiệp vụ hoặc dữ liệu đang dùng trong lượt này.

152 test Node hiện có, thuộc 37 file `.test.mts`, đều PASS, không skip. Đây là kiểm tra bổ sung của repository hiện tại, **không thay thế** các bài Django/PostgreSQL/MinIO trong README. Kết quả các lượt audit trước không được nhập làm kết quả của lượt kiểm chứng này.

Skill áp dụng: `ponytail`, dùng kiểm tra nhỏ nhất đủ tạo bằng chứng và không refactor khi chưa có verdict. Giống kiểm định xe: phiếu kiểm tra đèn không thay được phép thử phanh trên đường thử.

## Thực hiện theo thứ tự tài liệu

| Bước README | Đã làm | Trạng thái và điều kiện tiếp tục |
|---|---|---|
| 1. Bảo vệ dữ liệu | Không chạy test hoặc cleanup trên DB/object storage đang phục vụ ứng dụng; không đọc/xuất credential. Phát hiện PostgreSQL 18 `initdb`/`pg_ctl` trên máy. | Chưa dựng cluster thử riêng vì chưa có test kit để kiểm tra và chạy. Chỉ có loopback trong cấu hình không chứng minh DB cô lập. |
| 2. Chạy Django kit | Tìm file kit trong Downloads, thư mục attachment được cung cấp và repository. | Thiếu `RUN_AUDIT.ps1`, package `audit_verification` và cả bốn công cụ Python được README liệt kê. Thư mục `BLUEDRIVE_AUDIT_20261108_164650` là source snapshot, không phải verification kit. Không chạy lệnh test thay thế. |
| 3. Verdict A01–A12 | Lập bảng bên dưới và CSV kèm theo, phân biệt bằng chứng hỗ trợ với kit gốc. | A01–A10 NOT_TESTED; A11 chưa đủ bằng chứng runtime; A12 có phát hiện inventory độc lập. |
| 4. A02 concurrency | Chưa chạy. | Cần kit gốc và PostgreSQL test cluster riêng; chạy test đơn trước, sau đó ít nhất 20 lượt hợp lệ. |
| 5. MinIO fault test | Đọc compose hiện tại: dùng volume `minio_data` cố định. Không khởi động hoặc gây fault trên volume này. `docker` không có trong PATH của shell kiểm tra. | Cần kit, MinIO/Toxiproxy riêng và xác nhận cô lập; T01–T05 vẫn chưa chạy. Không bật opt-in cho instance hiện có. |
| 6. A05/A10 tài nguyên | Chưa chạy fixture ZIP, tracemalloc hay RSS. | Cần test kit; không suy tài nguyên server từ 152 unit test frontend. |
| 7. A11 vận hành | Đọc boolean cấu hình local, không request storage và không kết nối DB. | TLS thực, SSE trên object, scanner fail-closed, restore và alert delivery chưa được kiểm chứng. |
| 8. Preflight A11/A12 | Chạy hai script hỗ trợ tự viết trong thư mục artifact, được ghi rõ không phải tool gốc. | Kết quả chi tiết bên dưới. |
| 9. Evidence | Lưu log Node, JSON inventory/config, CSV verdict, hash README và báo cáo. | Không có `django_a01_a10.txt` hoặc `BLUEDRIVE_MINIO_FAULT_*.json` vì các bài đó chưa chạy. |
| 10. Agent Skill | Ghi nhận quy trình có thể tái sử dụng. | Nên đóng gói sau khi có kit và kiểm chứng thành công môi trường DB/MinIO riêng; chưa tạo skill giả định quy trình đã được nghiệm thu. |

## Ma trận verdict

Các ID dưới đây giữ ý nghĩa của README; không coi setup thiếu hoặc test chưa chạy là lỗi ứng dụng đã xác nhận.

| ID | Result | Evidence | Repro Steps | Root cause | Decision |
|---|---|---|---|---|---|
| A01 | NOT_TESTED | Thiếu `test_findings.py` | Chạy `AuditLifecycleTests.test_A01_*` trong DB riêng khi có kit | Chưa xác định | Chưa kết luận GET status và race hết hạn. |
| A02 | NOT_TESTED | Thiếu bài concurrency gốc | Chạy `AuditConcurrentInitializationTests.test_A02_*`, xác minh fixture rồi lặp ≥20 lượt | Chưa xác định | Chưa kết luận side effect initiate/quota. |
| A03 | NOT_TESTED | Thiếu bài fault transaction | Chạy `AuditLifecycleTests.test_A03_*` | Chưa xác định | Chưa kết luận object deletion khi rollback. |
| A04 | NOT_TESTED | Thiếu bài cleanup interleaving | Chạy `AuditLifecycleTests.test_A04_*` | Chưa xác định | Chưa kết luận cleanup/publication race. |
| A05 | NOT_TESTED | Thiếu `test_content_listing.py` | Chạy `AuditSharedArchiveTests.test_A05_*` với fixture nhỏ mặc định | Chưa xác định | Chưa có tracemalloc/RSS/budget. |
| A06 | NOT_TESTED | Thiếu contract test gốc | Chạy `AuditListingContractTests.test_A06_*` | Chưa xác định | Chưa xác nhận page_size/next_cursor. |
| A07 | NOT_TESTED | Thiếu bài shared ZIP/FileVersion | Chạy `AuditSharedArchiveTests.test_A07_*` | Chưa xác định | Chưa xác nhận nội dung ZIP phiên bản mới. |
| A08 | NOT_TESTED | Thiếu bài RBAC gốc | Chạy `AuditWorkspaceTreeTests.test_A08_*` | Chưa xác định | Chưa kết luận Viewer override theo fixture kit. |
| A09 | NOT_TESTED | Thiếu bài worker claim gốc | Chạy `AuditWorkerFencingTests.test_A09_*`; T05 cần lab riêng | Chưa xác định | Không dùng test worker cũ để tuyên bố bài kit đã đạt. |
| A10 | NOT_TESTED | Thiếu bài storage reader gốc | Chạy `AuditFallbackReadTests.test_A10_*` | Chưa xác định | Chưa xác nhận bounded read theo fixture kit. |
| A11 | INCONCLUSIVE | `runtime_a11_supporting.json`: chỉ cấu hình trong tiến trình kiểm tra local | Cần tool gốc và các cổng kiểm chứng thực ở bước 7 | Chưa đủ evidence runtime; local chưa cấu hình SSE/scanner | Không chứng nhận production readiness. |
| A12 | CONFIRMED — inventory hỗ trợ | `inventory_a12_supporting.json`: 37 file, 14 unit script, 20 file chưa được script tham chiếu trực tiếp | Đọc package.json, liệt kê `.test.mts`, đối chiếu đường dẫn; chạy toàn bộ bằng Node | Chưa có lệnh npm bao phủ đầy đủ 37 file hiện có | Phát hiện thiếu đường chạy test đầy đủ được xác nhận bằng inventory độc lập; tool gốc chưa chạy. Không tự sửa package trong lượt verification này. |

## Bằng chứng frontend

Lệnh chạy thực tế trong script hỗ trợ:

```text
node --experimental-transform-types --test --test-reporter=tap <37 đường dẫn .test.mts đã liệt kê>
```

Kết quả: **152 tests, 152 pass, 0 fail, 0 skipped**, exit 0, thời gian test khoảng 1,35 giây. Có cảnh báo Node về experimental transform và module type; không sửa cấu hình module chỉ để xóa cảnh báo.

14 npm unit script có tham chiếu trực tiếp tổng cộng 17/37 file; danh sách 20 file còn lại có trong JSON. Tất cả 37 file đã được chạy trực tiếp trong lượt này. Inventory này không đánh giá chất lượng/assertion/coverage của test, và không tuyên bố không có cơ chế CI bên ngoài repository.

## Bằng chứng cấu hình local

Lần import settings theo môi trường shell mặc định bị production guard từ chối với lỗi yêu cầu public storage endpoint hợp lệ/HTTPS trong production. Không vô hiệu hóa guard hoặc sửa `.env`.

Sau đó chạy một tiến trình kiểm tra với `DEBUG=true` rõ ràng, chỉ nạp settings, không `django.setup()`, không gọi DB hoặc MinIO. JSON ghi profile này để tránh nhầm với cấu hình tiến trình server đang chạy:

- Django import được; DB host cấu hình là loopback, chưa xác minh là cluster riêng.
- Endpoint storage cấu hình HTTP; TLS verify được bật trong cấu hình, nhưng chưa có handshake HTTPS.
- SSE và scanner chưa được cấu hình trong profile local này.
- Secure cookie tắt trong profile local; không suy thành lỗi cấu hình production.
- Live TLS, object SSE, scanner fail-closed, backup restore và alert delivery đều chưa được chứng thực.

Không lấy cờ boolean settings làm bằng chứng dịch vụ hoạt động. Giống biển “có bình chữa cháy”: vẫn cần thử đúng thiết bị và quy trình trước khi nghiệm thu.

## Artifact và điều kiện tiếp tục

Artifact tại `frontend/test-results/readme-verification/`:

- `frontend-inventory.cjs`: script hỗ trợ inventory và chạy test Node, không phải tool kit gốc.
- `runtime-preflight.py`: script đọc boolean cấu hình, không phải tool kit gốc.
- `frontend-node-tests.txt`: TAP log đầy đủ.
- `inventory_a12_supporting.json`: danh mục 37 file và 20 file chưa có unit script tham chiếu trực tiếp.
- `runtime_a11_supporting.json`: boolean cấu hình, không có credential/object/presigned URL.
- `A01_A12_VERDICT.csv`: verdict của lượt này.
- `evidence-manifest.json`: hash tài liệu đầu vào và artifact hỗ trợ.

**Đầu vào còn thiếu:** ZIP/thư mục `BLUEDRIVE_AUDIT_VERIFICATION_20261108` thực tế, gồm `RUN_AUDIT.ps1`, `backend/audit_verification/` và `tools/`. Khi có kit, đọc runner/tests trước, dựng PostgreSQL cluster mới riêng, xác minh DB test chưa tồn tại, chặn S3 ngoài mock, rồi thực hiện lần lượt bước 2–7 và cập nhật cùng bảng verdict. Không tự viết lại test có cùng tên để thay cho bộ gốc.

Không sửa application source vì README yêu cầu vòng verification trước quyết định refactor và hiện chưa có bằng chứng kit để xác định thay đổi nào cần thực hiện.
