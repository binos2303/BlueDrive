# BlueDrive — Kết quả kiểm chứng kit A01–A12, 08/11/2026

## Kết luận

Đã nhận và đọc `BLUEDRIVE_AUDIT_VERIFICATION_20261108.zip`, chạy nguyên 10 test Django của kit trên **PostgreSQL 18.6 cluster mới, riêng biệt**, rồi chạy các lượt bổ sung để phân xử lỗi fixture và đo concurrency. Không sửa application source, `.env`, migration hoặc test gốc trong lượt kiểm chứng này. Các thay đổi của lượt này chỉ gồm báo cáo và công cụ/bằng chứng trong thư mục artifact.

Lượt gốc: **10 test, 7 assertion FAIL, 2 ERROR**. A08 vừa FAIL assertion vừa ERROR khi kiểm tra FK ở teardown; vì vậy không được cộng các số này thành số test độc lập. A05 mặc định không đặt budget và A09 hoàn thành thành công. Sau phân xử:

- A01, A02, A03, A07, A08, A10: xác nhận hành vi không đáp ứng bất biến trong phạm vi fixture; không đồng nghĩa đã chạy S3 thật.
- A05: xác nhận vượt ngân sách Python 16 MiB được chọn cho fixture 4×2 MiB; chưa phải phép đo production RSS.
- A06: xác nhận endpoint hiện tại bỏ qua `page_size=3`; cần thống nhất contract trước khi coi tên/thể thức pagination trong kit là API bắt buộc.
- A04: test có vấn đề về cách chèn interleaving; source có thao tác storage trước khóa/recheck, nhưng chưa chứng minh mất dữ liệu PRIMARY sau publication bằng race hợp lệ.
- A09: không tái hiện stale-claim publication trong bài DB/mock của kit.
- A11: chỉ có preflight settings local; các cổng vận hành thực vẫn chưa được kiểm chứng.
- A12: **không tái hiện thiếu `.test.mts` ở repo gốc**; công cụ gốc tìm thấy 37 file. Snapshot đã chia sẻ thiếu file không chứng minh repo hiện tại thiếu file.

Skill áp dụng: `ponytail`, ưu tiên bằng chứng trực tiếp và giữ nguyên test gốc. Giống kiểm định xe: cần tách lỗi của xe, lỗi dụng cụ đo và bài thử chưa làm, thay vì coi mọi đèn đỏ là cùng một nguyên nhân.

## 1. Môi trường và giới hạn an toàn

- Giải nén vào `frontend/test-results/audit-kit-20261108/kit/`, kiểm tra mọi entry nằm trong đích giải nén. Đối chiếu hash từng file với ZIP sau khi chạy; không sửa test gốc.
- Không dùng `RUN_AUDIT.ps1` làm lớp điều phối: script đó đổi DB_NAME/DB_HOST nhưng không tự tạo cluster riêng, không chặn S3 ngoài mock, và ghi thẳng vào Downloads. Thay bằng `run_isolated.py` bao ngoài; các module/fixture/assertion của kit vẫn nguyên bản.
- Mỗi lượt chạy có PostgreSQL cluster mới, role thử mới, password ngẫu nhiên chỉ trong tiến trình/file tạm, cổng loopback riêng, database name ngẫu nhiên. Kiểm tra `SHOW data_directory` đúng thư mục do lượt đó tạo và test DB chưa tồn tại trước khi Django tạo DB. Không dùng `--keepdb`.
- Chỉ tiến trình kiểm tra đặt `DEBUG=true`, email locmem, MEDIA_ROOT tạm và thêm `testserver` vào ALLOWED_HOSTS. Không sửa server đang chạy hoặc `.env`.
- Chặn `botocore.httpsession.URLLib3Session.send`; request S3 ngoài mock sẽ thành lỗi kiểm tra. Không gửi email thật.
- Mỗi cluster thực thi test đều đã dừng và thư mục tạm đã xóa; `isolation.json` của từng lượt ghi kết quả. Không chạm database hoặc bucket ứng dụng.
- Lần dựng hạ tầng đầu gặp `pg_ctl` giữ PIPE trên Windows trước khi test bắt đầu. Đã dừng đúng cluster đó, chuyển đầu ra daemon sang file và chạy lại. Một lỗi console CP1258 sau lượt baseline không làm mất log UTF-8 hoặc kết quả test. Inventory cũng được chạy lại với UTF-8 sau lỗi in console. Đây là lỗi công cụ điều phối, không tính vào lỗi nghiệp vụ.

## 2. Các lượt đã thực thi

| Lượt | Test thực thi | Kết quả |
|---|---:|---|
| Baseline nguyên kit | 10 | 7 assertion FAIL, 2 ERROR; A08 có cả FAIL và lỗi FK teardown; A05/A09 hoàn thành thành công |
| A02 lặp độc lập | 20 | **20/20 FAIL**, mỗi lượt ghi nhận 2 provider initiations; không có lỗi thread/timeout trong 20 lượt |
| A07 chạy riêng | 1 | FAIL: HTTP 302 thay vì 200, loại trừ lỗi setup connection của lượt gộp |
| A08 fixture hợp lệ, bài hỗ trợ riêng | 1 | FAIL sau khi kiểm tra FK thành công: Viewer override bị bỏ qua |
| A05 ngân sách 16 MiB | 1 | FAIL: 24.042.421 bytes, khoảng **22,93 MiB**, vượt 16 MiB |
| Inventory gốc A11/A12 | 1 công cụ | Thành công: 37 `.test.mts`, `source_incomplete_for_frontend_tests=false` |
| Runtime preflight gốc A11 | 1 công cụ | Thành công với profile local `DEBUG=true`; chỉ đọc settings, không attestation dịch vụ |

Tổng cộng **33 lượt test Django**, không phải 33 kịch bản khác nhau. Baseline A02 thêm một lần tái hiện ngoài 20 lượt lặp. Không chạy lại toàn bộ suite ứng dụng hoặc 152 test Node vì lượt này không sửa source ứng dụng; các kết quả cũ không được nhập vào số test của lượt này.

## 3. Ma trận verdict và quyết định

| ID | Result | Evidence | Repro Steps | Root cause / giới hạn | Decision |
|---|---|---|---|---|---|
| A01 | CONFIRMED | Baseline: session từ UPLOADING thành EXPIRED sau GET | `AuditLifecycleTests.test_A01_*` | `files/upload_api.py:524` thực hiện save, storage cleanup, quota release trong GET; chưa chạy T01 hai connections với finalizer | Ưu tiên cao: tách status chỉ đọc, thống nhất expiry/cleanup có claim và kiểm tra race trước nghiệm thu |
| A02 | CONFIRMED | Baseline và 20/20 lượt riêng: 2 initiations/session | `AuditConcurrentInitializationTests.test_A02_*`, `AUDIT_REPETITIONS=20` | `_initialize_upload_session` ở `upload_api.py:58` dựa snapshot cũ, không reload/serialize init session; quota assertion cuối không được chạy vì assertion initiate đã FAIL | Ưu tiên cao: serialize init theo session và kiểm tra lại state; còn cần T02 live để chứng minh không có multipart orphan |
| A03 | CONFIRMED, phạm vi thứ tự xóa | Baseline: `delete_object` đã gọi 1 lần trước lỗi pre_delete; FileVersion còn tồn tại | `AuditLifecycleTests.test_A03_*` | `permanent_delete.py:52` xóa vật lý trước transaction metadata ở dòng 82; test chưa xác nhận object thật mất và không chứng minh StorageLocation còn AVAILABLE sau lỗi | Cần mô hình DELETE_PENDING bền vững và retry sau commit; không coi transaction PostgreSQL có thể rollback S3 |
| A04 | INCONCLUSIVE về race publication | Baseline gọi delete 1 lần; source cleanup storage ở dòng 29–31, khóa DB sau đó ở dòng 32 | `AuditLifecycleTests.test_A04_*` | Hook chỉ đổi state AVAILABLE **bên trong delete_object**. Nếu delete không xảy ra, hook không chạy và assertion AVAILABLE cũng FAIL. Chưa có publication commit độc lập hợp lệ | Giữ cảnh báo thứ tự từ source; viết bài Barrier/2 connections hợp lệ trước kết luận mất PRIMARY; không sửa ứng dụng để chạy theo fixture này |
| A05 | CONFIRMED vượt budget đã chọn | Baseline peak 22,82 MiB; chạy budget16 peak 22,93 MiB | `AuditSharedArchiveTests.test_A05_*`, `BLUEDRIVE_AUDIT_ZIP_PEAK_BUDGET_MIB=16` | Shared ZIP giữ payloads và ZIP trong RAM; fixture dùng bytes ngẫu nhiên. Budget16 là lựa chọn thử từ README, chưa phải SLO sản phẩm | Cân nhắc spool/stream từng file; đo RSS, TTFB, throughput ở lab trước đánh giá capacity |
| A06 | CONFIRMED khả năng pagination chưa có | Baseline: 7 items dù `page_size=3` | `AuditListingContractTests.test_A06_*` | Endpoint `/drive/api/items/` chưa đáp ứng contract mà kit yêu cầu. Tài liệu v1 dùng `limit/cursor` và `page.next_cursor`, khác kit `page_size/next_cursor` | Chốt contract hiện hành, triển khai API và callers đồng bộ; không chỉ cắt 3 items làm UI mất phần còn lại |
| A07 | CONFIRMED với endpoint ZIP legacy | Lượt riêng: HTTP302 thay vì ZIP200 | `AuditSharedArchiveTests.test_A07_*` chạy riêng | `sharing/views.py:247` vẫn đọc encrypted `file_path` legacy; fixture versioned S3 mới không có đường dẫn đó | Dùng chung reader lưu trữ có kiểm tra phiên bản/quyền. Chưa chứng minh nội dung ZIP live; không suy ra mọi download presigned đều lỗi |
| A08 | CONFIRMED qua bài hỗ trợ hợp lệ | Kit gốc FAIL+FK ERROR; bài riêng có Membership/WorkspaceMembership và `check_constraints()` vẫn FAIL | `supporting_checks.ValidMixedOwnerTreeTests` | `sharing/services.py:366` chỉ duyệt child có cùng owner với root, bỏ qua child owner B có direct Viewer | Sửa whole-tree traversal theo tenant/workspace và effective permission của mọi descendant; giữ đường workspace Editor/Admin và kiểm thử riêng |
| A09 | NOT_REPRODUCED | Baseline: original test `ok`, log claim superseded | `AuditWorkerFencingTests.test_A09_*` | 1 lượt DB/mock, đã ngăn metadata publication trong fixture đổi attempts; không có 2 worker process/S3 thật | Giữ cơ chế hiện tại; T05 nhiều worker và provider-side I/O vẫn chưa được chứng minh |
| A10 | CONFIRMED về unbounded read | Baseline: stream.read được gọi không có size | `AuditFallbackReadTests.test_A10_*` | `files/views.py:410,430` dùng `read()` toàn bộ; fixture không đo file lớn hoặc RSS | Cần reader streaming/spooling nhất quán và ràng buộc legacy AEAD; chỉ đổi sang read(chunk) rồi join vẫn giữ cả file trong RAM |
| A11 | INCONCLUSIVE | `runtime_a11_local.json`, `inventory_a11_a12.json` | Tool gốc, explicit local DEBUG=true | HTTP storage; SSE/scanner chưa cấu hình trong profile này; chưa attestation TLS/object/restore/alert | Không chứng nhận production readiness; cần lab/dịch vụ thật và bằng chứng vận hành |
| A12 | NOT_REPRODUCED | Inventory gốc có đủ37 file, package có script `.test.mts`, source_incomplete=false | `tools/audit_inventory.py --root <repo>` | Snapshot nguồn đã chia sẻ thiếu `.test.mts`; repo gốc có file. Tool chỉ kiểm hiện diện, không chứng minh từng script đúng | Không phục hồi hoặc viết lại test đang có. 20 file chưa được unit script tham chiếu trực tiếp là phát hiện hỗ trợ khác, không phải A12 của kit |

## 4. Phân xử chất lượng bộ kit

1. **A08 gốc thiếu fixture membership**: owner B thuộc tenant cá nhân khác nhưng được gán làm owner thư mục tenant A mà không tạo membership A. FK `folder_owner_membership_fk` lỗi ở teardown. Bài hỗ trợ không sửa file kit: tạo workspace riêng, membership B và role Editor, sau đó dựng cùng Editor-root/Viewer-child và kiểm tra constraint trước khi gọi hàm. Bài hợp lệ vẫn FAIL.
2. **A07 lỗi setup trong lượt gộp**: xuất hiện `OperationalError: the connection is closed` tại create_user. A05 ngay trước đó có `response.close()` trong TestCase; callback đóng request/connection là một nguyên nhân cần xem xét. Không gán setup error thành lỗi tải file. Chạy riêng A07 trên cluster mới thu được FAIL302, mới dùng kết quả riêng làm evidence nghiệp vụ.
3. **A07 chưa đủ fixture bytes cho đường reader mới**: mock được tạo ở `sharing.views.get_storage_adapter` bằng `create=True`, nhưng chưa thiết lập stream chứa `content`. Khi sửa reader, cần bài hỗ trợ tại đúng boundary để kiểm chứng ZIP bytes thật; không được làm response200 giả để qua test.
4. **A04 hook không độc lập với hành vi bị cấm**: chưa dùng FAIL này làm chứng minh race publication. Cần hai connections hoặc hook sau snapshot/trước kiểm tra claim, thay vì hook chỉ chạy khi delete đã xảy ra.
5. **Summarizer bỏ sót nhiều test**: regex gốc yêu cầu tên test và kết quả trên cùng dòng. Django verbosity2 có docstring và logging xen dòng, nên template ghi NOT_RUN cho nhiều bài thực sự đã chạy, kể cả A09. Giữ template nguyên bản, đối chiếu log và tạo CSV verdict đã phân xử riêng; không sửa tool gốc để che giới hạn.
6. **A12 cần hiểu đúng phạm vi**: báo cáo preflight trước khi có kit đã gắn inventory thiếu đường chạy npm với nhãn A12. Sau khi đọc kit, điều chỉnh: A12 gốc là thiếu test files trong nguồn đã chia sẻ; vấn đề đó không tái hiện ở repo thật. Nhận xét 20 file chưa được npm script tham chiếu vẫn chỉ là phát hiện bổ sung.

## 5. Các bước MinIO/vận hành chưa chạy

Chưa chạy `minio_fault_probe.py` và T01–T05 E2E. Shell không có Docker trong PATH, đường cài Docker mặc định không tồn tại; chưa xác định được MinIO/Toxiproxy lab riêng cùng credential thử. Không chuyển fault test sang bucket ứng dụng chỉ vì endpoint local. Kit yêu cầu lab riêng, loopback và volume mới; compose hiện tại dùng `minio_data` cố định nên không được dùng trực tiếp cho fault test.

Không có `BLUEDRIVE_MINIO_FAULT_*.json`; không có bằng chứng TLS handshake/chứng chỉ, SSE qua HEAD Object, scanner fail-closed, backup/restore hoặc alert delivery. Preflight A11 không mở kết nối DB/storage; `connection.vendor` chỉ đọc loại backend đã cấu hình. `DEBUG=true` được đặt riêng cho tiến trình kiểm tra, không dùng để kết luận server production đang chạy ở chế độ này.

Các phép đo 10k/100k items, RSS/TTFB/p95/p99, tải file lớn và worker thật chưa thực hiện. Không trình bày là PASS hoặc thay bằng test mock. Những phần này là điều kiện còn lại để hoàn thành toàn bộ README, không phải đã nghiệm thu.

## 6. Đề xuất thứ tự sửa sau vòng kiểm chứng

Ưu tiên A01/A02/A03 và xác minh A04 trước vì tác động vòng đời/quota/object; tiếp theo A08 để bảo đảm quyền trên toàn cây; gộp A05/A07/A10 quanh cùng reader/ZIP để tránh viết nhiều đường đọc khác nhau; sau đó hoàn thiện A06 đồng thời API và UI. Giữ A09 và tăng kiểm chứng nhiều worker khi có lab.

Ví dụ thực tế: metadata và object giống sổ kho và hàng trong kho. Xóa hàng trước khi giao dịch cập nhật sổ hoàn tất sẽ không được “hoàn tác” bằng rollback của sổ. Vì vậy A03 cần trạng thái xóa bền vững và retry, thay vì chỉ bọc thêm transaction quanh lời gọi S3. Tương tự, A02 cần một quyền khởi tạo duy nhất, giống một phiếu xuất kho không được hai nhân viên cùng sử dụng.

Chưa refactor ứng dụng trong lượt này: một số đề xuất chạm contract API, caller, quyền và cleanup, trong khi kit có các hạn chế đã nêu. Bảng verdict này là mốc bằng chứng trước khi sửa, theo bước9 README; giữ nguyên các test gốc để so sánh hồi quy.

Có thể đóng gói lớp điều phối thành Agent Skill `BlueDrive Fault-Driven Architecture Audit` sau khi hoàn tất cả nhánh MinIO lab và xác minh cleanup: kiểm tra kit/hash → cluster riêng → test gốc → phân xử fixture → test bổ sung → verdict → sửa tối thiểu → chạy hồi quy.

## 7. Bằng chứng

Thư mục workspace: `frontend/test-results/audit-kit-20261108/`.

- `django_a01_a10.txt`: baseline nguyên kit, 10 test.
- `a02-repeat20/django_a01_a10.txt`: 20 lần nguyên test concurrency.
- `a07-solo/django_a01_a10.txt`: A07 riêng.
- `a08-valid-fixture/django_a01_a10.txt`: bài hỗ trợ A08 với FK hợp lệ.
- `a05-budget16/django_a01_a10.txt`: ngân sách16 MiB.
- `isolation.json` ở baseline và từng thư mục lượt: xác nhận cluster riêng, DB chưa tồn tại, dừng và dọn.
- `inventory_a11_a12.json`, `runtime_a11_local.json`: output tool gốc.
- `A01_A12_VERDICT_TEMPLATE.csv`: output summarizer gốc, có hạn chế parser.
- `A01_A12_VERDICT_REVIEWED.csv`: kết luận đã phân xử.
- `run_isolated.py`, `supporting_checks.py`: lớp điều phối và test hỗ trợ, tách khỏi kit.
- `evidence-manifest.json`: SHA-256 ZIP, file kit, source liên quan và artifact. Credential/data directory không được đóng gói.

Giữ báo cáo preflight trước đó làm lịch sử; báo cáo này cập nhật trạng thái sau khi đã nhận kit, không ghi đè báo cáo cũ.
