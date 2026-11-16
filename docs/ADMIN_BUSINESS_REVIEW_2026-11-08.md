# BlueDrive — Rà soát và hoàn thiện nghiệp vụ admin

Ngày: 08/11/2026. Workspace: `C:\Users\dang2\Project\SecureDrive`.

## Kết luận và phạm vi

Đã kiểm kê 23 page entry point của admin, kiểm tra 28 URL gồm route động và bookmark cũ, đối chiếu API/quyền của các nghiệp vụ hiện có, sửa các điểm đã xác nhận và nghiệm thu trên Chrome desktop/mobile. Mục tiêu là làm đúng các thao tác đang có, bổ sung khả năng theo dõi cần thiết và bỏ lối vào tính năng chưa hoạt động; không mở rộng thành dự án backup/monitoring mới.

Đã sửa phân loại phiên đăng nhập, khóa form/hộp thoại đang xử lý, tìm kiếm audit và đường tới audit gói dung lượng. Đã bổ sung số liệu upload processing vào Dashboard/System Health. Đã bỏ ba mục chưa có dịch vụ thật khỏi menu chính và xóa implementation audit cũ không còn caller.

Ví dụ thực tế: bảng điều khiển cần giống tủ điều khiển thật — tên công tắc đúng với quyền, nút bấm có chức năng và đồng hồ có nguồn dữ liệu. Một trang chỉ có trạng thái Unknown không nên chiếm chỗ như một chức năng vận hành đã sẵn sàng.

## 1. Quyết định theo từng nhóm nghiệp vụ

| Nhóm | Quyết định | Lý do và ranh giới |
|---|---|---|
| Dashboard | Giữ, bổ sung upload processing | Có số liệu PostgreSQL thật. Sửa caption file thành Files outside Trash để không đồng nhất metadata với kết quả kiểm tra nội dung/storage |
| Users | Giữ suspend/reactivate và observed sessions | Cần lý do, CSRF và audit; bảo vệ staff/superuser, không xóa file khi khóa tài khoản |
| Platform Admins | Giữ invite/reinvite/disable cho Super Admin | Danh tính quản trị riêng, không tự nâng tài khoản Drive thành admin; không gửi email thật trong nghiệm thu mutation |
| Organizations | Giữ inventory chỉ đọc | Có dữ liệu thật; không thêm thao tác can thiệp nội bộ hoặc quota tổ chức |
| Workspaces | Giữ inventory, scope, role counts | Có API metadata thật; quyền cộng tác vẫn thuộc các luồng Workspace, không biến platform role thành quyền đọc nội dung |
| Files | Giữ metadata/details và quyền recovery hiện có | Super Admin có trash/restore/purge theo policy hiện hành; purge cần nhập tên chính xác và audit. Không thêm quyền xem bytes file |
| Roles & Permissions | Giữ tham chiếu chính sách và số lượng assignment | Đây là bản mô tả quyền thật, không tạo role giả hay công cụ cấp quyền tùy ý |
| Storage plans | Giữ luồng tạo/gán gói đã sửa | Chỉ cấp gói cho Personal Drive/Workspace cá nhân; không đưa Custom quota hoặc quota tổ chức trở lại |
| User Activity / Admin Audit | Giữ, bổ sung tra cứu và liên kết ledger | Có nguồn sự kiện thật; chỉ chiếu trường cho phép, không trả metadata thô |
| Settings | Giữ display name và policy đang có | Không thêm toggle giả cho session policy, maintenance hay security cấu hình ngoài runtime |
| System Health | Giữ, bổ sung Refresh và backlog | Dữ liệu job giúp phát hiện công việc tồn đọng; không suy từ API đang trả lời rằng toàn bộ worker/storage khỏe |
| Security Alerts | Bỏ khỏi menu chính | Chưa có detection pipeline/API cảnh báo thật |
| Storage Topology | Bỏ khỏi menu chính | Chưa có host/MinIO telemetry để vẽ thiết bị thật |
| Backups | Bỏ khỏi menu chính | Chưa có dịch vụ chạy backup/restore thật |

Các URL của tính năng chưa kết nối vẫn trả trạng thái rõ để bookmark cũ không dẫn tới chức năng giả. Không xóa dữ liệu backup, cảnh báo hay thiết bị trong database; không có thao tác triển khai những dịch vụ đó trong lượt này.

## 2. Những điểm đã sửa và vì sao

### A01 — Bộ lọc phiên đăng nhập không khớp danh tính admin

Trước sửa, điều kiện loại khỏi `scope=users` chỉ loại người vừa staff vừa superuser; Platform Admin có staff nhưng không superuser vẫn xuất hiện trong nhóm người dùng thường. `scope=admins` lại chỉ lấy staff superuser, nên thiếu Platform Admin chuyên biệt.

Đã đồng bộ với directory: Users chỉ chứa tài khoản không staff và không superuser; Admins chứa staff superuser hoặc tài khoản có PlatformAdminIdentity. Thêm related loading cho identity và phân loại `account_type=admin` cho dedicated admin. Staff không đăng ký identity vẫn được bảo vệ và không bị coi là user thường. Quyền revoke server-side vốn đã chặn staff/superuser; đây không phải bằng chứng đã tồn tại đường vượt quyền revoke.

### A02 — Thao tác đang lưu chưa khóa giao diện đầy đủ

Các callback đóng đã có một số guard nhưng nút Close vẫn hiện khả dụng, input vẫn sửa được và submit invitation chưa có guard tức thời độc lập với render.

Đã dùng `closeDisabled` của Dialog chung cho invitation, account action và hai lớp dialog session; khóa trường đang gửi; thêm guard ref cho thao tác Users/Admins để hai submit liên tiếp không gửi hai request. Sau lỗi giữ nguyên dữ liệu/lý do và hiển thị lỗi trong dialog. Session load lỗi có Retry sessions thay vì buộc đóng/mở lại hoặc reload trang.

### A03 — Chưa có tín hiệu upload processing cho quản trị

Đã bổ sung vào overview các count pending/processing/failed/stale của UploadFinalizationJob, số session verifying/scanning và thời điểm cập nhật cũ nhất của job đang hoạt động. Dùng hai aggregate query; không tải nội dung file hay gọi storage provider để lấy số liệu này.

Ngưỡng stale 10 phút được đưa về một hằng dùng chung giữa worker reclamation và admin API. Dashboard/System Health dùng cùng overview client và component hiển thị. Failed jobs được ghi rõ là lịch sử còn lưu, không phải số lỗi mới; stale không được trình bày như bằng chứng worker offline. Zero job không phải chứng nhận worker đang chạy.

### A04 — System Health thiếu khả năng thử lại và có lối vào trang chưa hoạt động

Đã thêm Refresh, xóa trạng thái cũ khi bắt đầu tải lại và phân biệt unavailable/not verified. Bỏ link quảng bá topology chưa có dữ liệu. Dashboard trỏ sang System Health thật thay cho topology placeholder và bỏ hướng dẫn đường dẫn backend khỏi thông báo lỗi người dùng.

### A05 — Audit khó tìm và ledger gói bị tách mà thiếu đường nối

Tìm kiếm Admin Audit Logs nay hỗ trợ actor/account, reason và file ID dạng số chính xác trên sự kiện file. Không tìm tùy ý trong metadata, không đổi allowlist trả dữ liệu. Thêm link Storage plans and allocation audit tới ledger hiện có; không tạo thêm nguồn audit cạnh tranh hoặc sao chép lịch sử tổ chức vào platform quota.

### A06 — Menu đặt các trang chưa có dịch vụ ngang với chức năng thật

Bỏ Security Alerts, Storage Topology, Backups khỏi menu chính. Giữ các route cũ có thông báo unavailable, các route hạ tầng sâu vẫn nói Unknown. Không hiển thị số 0 như thể đã kiểm tra và không thêm nút chạy dịch vụ giả.

### A07 — Hai implementation audit không cùng quy tắc

Đã xác nhận `admin_api.admin_audit_view` không còn route/caller trong repository và xóa implementation cũ này. Nó từng serialize raw metadata, nhưng endpoint đang đăng ký từ trước đã là implementation allowlist trong `admin_logs_api`; không khẳng định route hiện hành đã làm lộ metadata. Xóa mã chết để tránh nối lại nhầm và giữ một implementation audit chính.

Các điểm trên thuộc độ đúng nghiệp vụ, khả năng phục hồi và tính nhất quán. Không gán P0 hoặc tuyên bố có exploit khi chưa có bằng chứng.

## 3. Kiểm chứng

| Nhóm | Kết quả |
|---|---|
| Regression mới và nhóm admin/session/audit/recovery chọn lọc | 49/49 đạt |
| Toàn bộ backend | 448 ca: **439 đạt, 9 MinIO integration bỏ qua**, không lỗi |
| Kiểm tra lại audit/session sau khi xóa implementation cũ | 20/20 đạt |
| Browser với API giả lập | 66 ca được kiểm tra đạt: 28 URL × desktop/mobile và 5 luồng nghiệp vụ × desktop/mobile |
| Browser với API đăng nhập thật | **30/30 đạt**, 15 trang × desktop/mobile, chỉ đọc |
| TypeScript và ESLint các file frontend thay đổi | Đạt |
| Migration dry run | No changes detected |
| Impeccable detector trên source admin | Exit 0, `[]` |
| Diff whitespace check | Đạt |

Lượt browser giả lập đầu có 64/66 đạt; hai ca System Health vấp locator strict do Next.js có route-announcer `role=alert` riêng. Đã scope locator đúng thông báo sản phẩm, chạy lại hai ca đạt và kiểm tra cuộn tới cuối phần số liệu. Không tính các lượt chạy lặp như test mới.

Backend dùng PostgreSQL test có tên riêng, media tạm, email trong bộ nhớ, hasher nhanh chỉ trong tiến trình test và chặn storage HTTP chưa mock. Database test đã được hủy. Mutation browser dùng API giả lập; không mời admin, khóa tài khoản, revoke session hoặc purge file thật.

Đã dùng phiên admin thử có sẵn để kiểm tra GET API thực tế và render trên 15 trang: Dashboard, Users, Organizations, Workspaces, Files, Permissions, Activity, Audit, Settings, System Health và năm trang quota/gói. Browser test chặn mutation tài khoản trước khi gửi. Không ghi thông tin đăng nhập/cookie/token vào báo cáo hay Downloads.

Các ca UI dùng desktop 1440×900 và mobile mô phỏng 390×844, kiểm tra root không tràn ngang và không có JavaScript crash. Có ảnh cho toàn bộ route; đã xem trực tiếp các ảnh đại diện menu, System Health cả phần đầu/cuối, Users, Files và Audit, gồm dữ liệu API thật. Chưa dùng thiết bị di động thật, NVDA/VoiceOver hoặc đo WCAG toàn diện. Detector non-HTML là kiểm tra pattern source; `[]` không chứng nhận UX/a11y hoàn hảo.

## 4. Tổ chức code và hợp đồng

- `backend/accounts/admin_api.py`: thống kê job và scope session.
- `backend/accounts/admin_logs_api.py`: audit lookup có kiểm soát.
- `backend/accounts/test_admin_business_review.py`: regression mới.
- `backend/files/models.py`, `management/commands/finalize_uploads.py`: ngưỡng stale dùng chung, không đổi schema.
- `frontend/lib/admin-overview-service.ts`: type/client overview chung; `admin-user-service.ts` tái sử dụng.
- `frontend/components/admin/UploadFinalizationStatus.tsx`: số liệu vận hành dùng chung.
- `PlatformDashboard.tsx`, trang System Health: render, retry và trạng thái dữ liệu.
- `UserDirectory.tsx`, `UserSessionsDialog.tsx`: pending guard, khóa form và phục hồi lỗi.
- `AdminLogDirectory.tsx`: tìm kiếm/đường dẫn audit.
- `frontend/components/layout/AdminConsole.tsx`: menu có chức năng khả dụng.
- `frontend/e2e/admin-business.spec.ts`, `admin.spec.ts`: inventory, workflow và nghiệm thu chỉ đọc.
- `docs/API_CONTRACT_V1.md`: addendum implementation được đồng bộ.

Working tree vốn đã có thay đổi từ các lượt trước. Báo cáo này chỉ nhận là bản sửa của lượt rà soát admin, không nhận toàn bộ Git diff là thay đổi mới.

## 5. Bằng chứng và giới hạn còn lại

Artifact trong `frontend/test-results/`:

- `roadmap-repairs/admin-review-before.txt`: regression trước sửa.
- `roadmap-repairs/admin-review-backend.txt`, `admin-review-full.txt`, `admin-review-audit-final.txt`: kết quả backend.
- `roadmap-repairs/admin-impeccable-detector.json`: detector source.
- `admin-business-review/`: inventory và workflow với API giả lập.
- `admin-business-health-scroll/`: retry và cuộn tới cuối số liệu.
- `admin-business-live-final/`: 30 ca API đăng nhập thật, chỉ đọc.

Chưa triển khai hoặc nghiệm thu dịch vụ backup/restore, detection pipeline, host telemetry, MinIO health/metrics, email delivery thật hoặc 9 ca MinIO integration cần bucket riêng. Không kết luận production-ready hay worker đang khỏe từ count database. Chưa benchmark aggregate trên dữ liệu lớn hoặc đo p95/p99; khi job history tăng cần đo trước khi thêm cache/counter/queue khác.

Các công cụ vận hành ở ngoài admin như phục hồi job, backup và cấu hình bảo mật vẫn cần runbook/deployment riêng. Trong lượt này không restart worker/database/MinIO, không đổi quota tổ chức và không mở rộng quyền platform vào nội dung file.

Skill đã dùng: ponytail cho KISS/DRY và sửa điểm chung; impeccable phần audit/harden/clarify cho inventory, trạng thái lỗi, pending, menu và kiểm tra render. Quy trình inventory route → capability/API → mutation cô lập → UI nhiều kích thước → live GET → báo cáo có thể đóng gói thành Agent Skill dùng lại.
