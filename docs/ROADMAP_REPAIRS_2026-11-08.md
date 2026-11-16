# BlueDrive — Sửa chữa sau thẩm định, đợt 1

Ngày: 08/11/2026. Đối chiếu: [báo cáo thẩm định](./ROADMAP_APPRAISAL_2026-11-08.md).

## Kết quả và phạm vi

Đã sửa quyền tại bước publication, phục hồi job finalization, bảo vệ kết quả trước lượt worker cũ, quyền quản lý thư mục của Workspace Editor và truy vấn lặp của listing Workspace thông thường. Đã bổ sung thông báo upload cho trường hợp đích lưu không còn ghi được. Đây là đợt sửa các lỗi đã tái hiện, chưa phải hoàn tất mọi hạng mục trong roadmap.

Giữ Next.js, Django, PostgreSQL, storage adapter, job và quota hiện có. Không thêm queue, ledger hay framework mới. Không đổi kích thước part, giới hạn upload, schema database hoặc cấu hình bucket. Roadmap gốc trong Downloads được giữ nguyên.

Ví dụ thực tế: trước đây hệ thống đã có sổ giữ chỗ và quy trình giao hàng. Đợt này sửa việc kiểm tra quyền khi bàn giao, nhận diện đơn đã giao sau khi máy khởi động lại, và ngăn nhân viên của lượt xử lý cũ sửa kết quả của lượt mới.

## 1. D01 — Quyền phải còn hợp lệ khi publication commit

**Nguyên nhân:** API kiểm tra quyền khi nhận complete, nhưng worker chạy sau đó có thể dùng trạng thái/quyền đã cũ. Việc hạ Editor xuống Viewer hoặc archive Workspace trong thời gian chờ chưa chặn publication.

**Đã sửa:**

- Kiểm tra lại tài khoản khởi tạo, tenant membership, Workspace role/status và thư mục đích trước khi ghi PRIMARY và trước khi commit metadata.
- Đọc lại dữ liệu quyền từ database. Không tin đối tượng actor, Workspace hay folder được giữ từ trước thao tác S3.
- Khóa các hàng Workspace, Tenant, user, Membership và WorkspaceMembership trong transaction ngắn. Việc update/revoke các hàng đó có thứ tự rõ với publication. Không giữ các khóa này trong lúc copy S3.
- Dùng lỗi `destination_not_writable`; worker không công bố File/Version/Location, trả reservation và xử lý object thất bại qua cơ chế cleanup/quarantine hiện có.
- Làm mới folder đích ở lần kiểm tra cuối để phát hiện folder đã vào Trash hoặc đổi scope trong lúc copy.

**Policy áp dụng:** quyền ghi phải còn hiệu lực đến lúc publication commit. Nếu revoke/archive commit trước, publication bị từ chối. Nếu publication commit trước, thao tác revoke sau đó không xóa file đã tạo; mọi lần truy cập tiếp theo vẫn qua ACL hiện hành.

**Kiểm chứng:** downgrade/archive trước copy, thay role/archive trong copy, tenant membership bị revoke, tài khoản bị vô hiệu hóa, folder vào Trash trong copy. Test dùng hai kết nối PostgreSQL xác nhận những hàng quyền cùng session/job không thể bị khóa để update từ kết nối khác tại commit; callback copy S3 xác nhận không nằm trong transaction.

**Giới hạn:** test đổi trạng thái giữa copy và commit dùng callback storage giả lập. Chưa chạy hai tiến trình worker thật cạnh tranh trên MinIO. Kiểm tra folder cuối không được mô tả là cơ chế khóa toàn bộ chuỗi tổ tiên khi có move/trash đồng thời.

File chính: `backend/files/finalization.py`, `backend/files/management/commands/finalize_uploads.py`, `backend/files/tests/test_finalization_permissions.py`.

## 2. D02 — Phục hồi job và bảo vệ lượt xử lý hiện hành

**Nguyên nhân:** sau crash ở khoảng metadata/quota đã commit nhưng job chưa DONE, retry lại staging đã xóa có thể làm job FAILED dù file vẫn AVAILABLE. Worker cũ cũng có thể ghi kết quả sau khi job đã được nhận lại.

**Đã sửa:**

- Khi claim job, khóa session rồi job theo cùng một thứ tự. Session AVAILABLE/COMPLETED được quy về job DONE ngay, không gọi storage, không tính thêm attempt và không thay quota đã consumed.
- Session terminal failed/canceled/expired được quy về job FAILED; giải phóng reservation còn tồn tại một cách idempotent. Điều này cũng xử lý khoảng trống từ các lần chạy cũ chưa quyết toán reservation.
- Dùng `attempts` hiện có để nhận diện lượt đang sở hữu job. Kiểm tra dấu nhận diện trước cập nhật tiến trình, scanner, publication và xử lý lỗi; chỉ lượt còn hiệu lực được sửa kết quả.
- Worker mất claim dừng ghi metadata/quota/job và không quarantine hoặc xóa object của lượt mới.
- Khi lỗi đến muộn nhưng session đã AVAILABLE/COMPLETED, hội tụ về DONE và giữ quota consumed.
- Cập nhật `updated_at` của claim tại các mốc database. Giữ retry có giới hạn cho lỗi storage tạm thời và lỗi tranh chấp uniqueness.
- Giữ nguyên mã `security_scan_rejected`, không ghi đè thành lỗi chung trong xử lý thất bại tiếp theo.

**Kiểm chứng:** crash sau publication; terminal failure; reclaim trong copy; lỗi worker cũ sau reclaim; lỗi đến sau commit; retry rồi thành công; scanner reject; scanner cũ bị thay lượt. Các ca kiểm tra cả trạng thái session/job, reservation và việc storage có bị gọi sai hay không.

**Giới hạn:** vẫn dùng timeout stale 10 phút. Timestamp được làm mới tại mốc database, chưa có heartbeat liên tục trong thao tác mạng dài. Dấu nhận diện bảo vệ kết quả database; không thể thu hồi một request S3 đã bắt đầu. Retry có thể chồng lấn I/O; chưa tuyên bố provider-side fencing hoặc bảo đảm không còn mọi object/version mồ côi.

File chính: `backend/files/finalization.py`, `backend/files/management/commands/finalize_uploads.py`, `backend/files/tests/test_finalization_recovery.py`.

## 3. D03 — Giảm truy vấn và nhất quán quyền Editor

**Nguyên nhân:** listing kiểm tra lại cùng quyền Workspace cho từng item; cây thư mục query từng node. `can_edit_folder_tree` trước đây chỉ đi theo đường Workspace cho chủ sở hữu, khiến Editor không quản lý được thư mục do đồng nghiệp tạo trong một số luồng.

**Đã sửa:**

- Ở listing Drive thông thường, tính role Workspace một lần cho request. Các item là con trực tiếp còn live trong đúng Workspace và thư mục đã được authorize; Editor/Admin dùng quyền đó cho danh sách.
- Người nhận direct share vẫn chạy kiểm tra từng item. Workspace Viewer vẫn kiểm tra grant riêng khi xác định quyền sửa, để không làm mất một Editor share trực tiếp hợp lệ.
- `can_edit_folder_tree` chấp nhận Workspace Editor/Admin trên cây live dù người tạo khác. Người chỉ có direct/inherited share vẫn chịu quy tắc Viewer override ở thư mục con.
- Duyệt cây theo từng tầng thay vì từng node. Chia frontier thành nhóm tối đa 1.000 ID; giữ phạm vi tenant/Workspace, bộ lọc owner/deleted, thứ tự cha-con và chống lặp khi cây có chu trình.

| Fixture cùng điều kiện | Trước sửa | Sau sửa |
|---|---:|---:|
| Listing Workspace Editor, 10 file ở root | 116 SQL | 18 SQL |
| Listing Workspace Editor, 30 file ở root | 313 SQL | 15 SQL |
| Root + 12 folder con, tổng 13 node | 13 SQL | 2 SQL |

Listing đo cả authentication/request overhead. Request đầu có thêm chi phí khởi tạo so với request sau; không suy ra rằng 30 file nhanh hơn 10 file. Đây là query count, không phải benchmark latency, p95/p99 hay tải đồng thời.

**Kiểm chứng:** Editor/Viewer, thư mục do đồng nghiệp tạo, Viewer có Editor share riêng, direct share với child Viewer override, private root, deleted ancestor, cây có chu trình, owner/deleted filters, thao tác copy/move/trash/restore cùng các test sharing hiện có.

**Chưa đóng toàn bộ D03:** chưa thêm pagination/sort phía server, chưa tối ưu toàn bộ Search/Recent/Starred và mọi trường hợp Viewer/direct-share. Cây sâu vẫn cần query theo số tầng; chưa có recursive CTE. Listing lớn vẫn cần bước phân trang có hợp đồng với selection/sort phía frontend.

File chính: `backend/dashboard/views.py`, `backend/folders/tree_service.py`, `backend/sharing/services.py`, `backend/dashboard/test_listing_queries.py`.

## 4. Thông báo upload và tài liệu API

Trước sửa, mọi failure ở finalization đều hướng dẫn sửa nội dung file. Với `destination_not_writable`, giao diện hiện nói đích lưu không còn ghi được và gợi ý chọn folder/Workspace khác hoặc nhờ quản lý khôi phục quyền. Lỗi security giữ thông báo và hướng xử lý riêng. Không hiển thị mã nội bộ như nội dung chính; không đưa ra nút retry tự động cho trường hợp này.

Đã kiểm tra Chrome ở viewport desktop 1440×900 và mobile mô phỏng 390×844, chụp ảnh và xem kết quả. Bốn ca browser dùng API giả lập, gồm hai loại failure ở hai kích thước. Nội dung hiển thị đủ, có `role="alert"` và không làm trang tràn ngang. Đây không phải nghiệm thu trên thiết bị di động thật hoặc công nghệ hỗ trợ.

Đã cập nhật addendum implementation trong `docs/API_CONTRACT_V1.md` về authorize-at-publication, failure code, recovery và giới hạn claim timeout.

File giao diện: `frontend/components/drive/upload-service.ts`, `frontend/e2e/upload-publication.spec.ts`.

## 5. Kiểm thử và bằng chứng

Kết quả cuối:

| Kiểm tra | Kết quả |
|---|---|
| Toàn bộ backend sau sửa isolation | 428 ca: **419 thành công, 9 bỏ qua**, không lỗi; 29,130 giây |
| 9 ca bị bỏ qua | MinIO integration cần bucket thử riêng và biến opt-in; chưa chạy trong đợt này |
| Regression cuối cho vùng thay đổi | **39/39 đạt**, 5,926 giây |
| Transaction concurrency, thứ tự thường | **2/2 đạt** |
| Transaction concurrency, thứ tự đảo | **2/2 đạt** |
| Chrome desktop/mobile, API giả lập | **4/4 đạt**, 10,5 giây; đã xem screenshot |
| TypeScript `tsc --noEmit` | Đạt |
| ESLint cho upload service và browser test mới | Đạt |

Các nhóm test có phần trùng nhau, không cộng các con số thành số lượng ca độc lập. Thời gian chạy test không đại diện hiệu năng ứng dụng.

Các artifact nằm tại `frontend/test-results/roadmap-repairs/`:

- `d01-before.txt`: 6 regression test thất bại trước sửa.
- `d01-after.txt`: 22 test chọn lọc đạt sau sửa quyền.
- `d02-before.txt`: 5 test recovery thất bại trước sửa.
- `d02-after.txt`: 27 test chọn lọc đạt.
- `d03-before.txt`: tái hiện N+1, số query cây và quyền quản lý folder của Editor.
- `d03-after.txt`: 49 test listing/collaboration/sharing đạt, có số query trước/sau.
- `combined-regression.txt`: 100 test tổng hợp đạt trước lần bổ sung cuối.
- `final-regression.txt`: 39 test trên phiên bản sửa chữa cuối, đạt.
- `backend-full.txt`: lượt chạy toàn bộ đầu tiên phát hiện lỗi isolation giữa hai TransactionTestCase; không che kết quả thất bại này.
- `concurrency-order.txt`, `concurrency-reverse.txt`: kiểm tra thứ tự thường/đảo của các ca transaction thật.
- `backend-full-final.txt`: lượt chạy toàn bộ sau sửa isolation.
- `ui-after/`: bốn ảnh browser nghiệm thu thông báo.

Test runner tạo database PostgreSQL tên riêng `test_sd_repair_*`, dùng media tạm và email trong bộ nhớ; database test được hủy khi kết thúc. Storage HTTP chưa mock bị chặn trong lượt chạy toàn bộ. Không chạy test MinIO thật trên bucket đang sử dụng. Lượt chạy toàn bộ đầu dùng password hasher thông thường; lượt chạy toàn bộ cuối dùng MD5PasswordHasher chỉ trong tiến trình test để giảm thời gian lặp. Cấu hình và mật khẩu người dùng thật không thay đổi; các test logic bảo mật vẫn chạy, đây không phải kiểm định độ mạnh của thuật toán hash password.

Lỗi isolation: thêm một TransactionTestCase mới làm lộ phụ thuộc thứ tự của test concurrency quota hiện có. Hai class transaction thật được bật `serialized_rollback` để khôi phục dữ liệu gói quota được migration tạo. Không sửa application provisioning để tự tạo lại plan khi thiếu; runtime vẫn giữ kiểm tra cấu hình plan nghiêm ngặt. Tham khảo [Django — Rollback emulation](https://docs.djangoproject.com/en/5.2/topics/testing/overview/#rollback-emulation).

## 6. Phần còn lại và điều kiện vận hành

1. Hoàn thiện D03 cho các view còn lại, đặc tả pagination/sort/selection rồi triển khai cùng frontend; không tự đổi response contract trong bản sửa N+1.
2. D04 giữ part 8 MiB như hiện tại. Trước khi tuning phải lưu part size bất biến theo session, cho client/worker cùng dùng và có compatibility cho session cũ. Đợt này không tăng part size hoặc concurrency.
3. Heartbeat/claim khi I/O kéo dài, kiểm thử nhiều worker thật và kiểm kê object/version mồ côi còn cần môi trường storage test riêng.
4. TLS/SSE/provider attestation, scanner thật, backup/restore DB-object-key, telemetry và runbook vẫn là các gate riêng trong roadmap. Chưa có cơ sở kết luận production-ready.
5. Source đã sửa cần được nạp lại bởi các tiến trình ứng dụng/worker. Đợt này không restart hay cấu hình lại worker, database hoặc MinIO đang phục vụ dữ liệu thật. Frontend cổng 3100 chỉ phục vụ kiểm thử API giả lập và đã được dừng sau nghiệm thu.
6. Một lượt script chọn file trước khi trang dev tải xong tài khoản/danh sách từng nhận lỗi mất file trong bộ nhớ. Sau khi chờ trạng thái tải xong, luồng chạy đến API và tái hiện được lỗi copy cần sửa. Chưa kết luận nguyên nhân lifecycle/hydration của hiện tượng sớm này; cần kiểm tra riêng trước khi tuyên bố xử lý hoàn chỉnh mọi tình huống khởi tạo/reload upload.

Skill đã áp dụng: `ponytail` cho thay đổi nhỏ đủ giải quyết nguyên nhân, `impeccable` phần clarify cho thông báo lỗi. Quy trình tái hiện → sửa chung → regression → kiểm tra browser → báo cáo có thể đóng gói thành Agent Skill dùng lại.
