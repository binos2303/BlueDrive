# Nghiệm thu trình duyệt BlueDrive — 07/11/2026

## Trạng thái cập nhật

Đã kiểm tra frontend `http://localhost:3000` và API `http://localhost:8000` bằng Playwright 1.65.0 với Google Chrome cài sẵn. Browser bridge vẫn lỗi; phương án Playwright được người dùng đồng ý. Chrome dùng hồ sơ kiểm thử riêng, người dùng đăng nhập thủ công ngoài sandbox; không sử dụng hồ sơ Chrome chính hoặc nhận mật khẩu qua chat.

**38/38 ca đạt trong lượt tổng hợp lúc 14:57–14:59 (UTC+7): 32 ca frontend/API mô phỏng và 6 ca API thật.** Desktop 1440×900 và mobile emulation 390×844, một worker, không tự retry; 0 skipped, 0 flaky, 0 unexpected. Kết quả ở `frontend/test-results/results.json` và `frontend/playwright-report/index.html`; không cộng các lượt chạy lại thành số ca độc lập.

Sau đó người dùng đã đăng nhập thêm tài khoản admin thử trong một Chrome profile riêng. Phần admin được bổ sung bên dưới; kết quả/ảnh của lượt 38 ca trước được giữ nguyên. Hai bộ kiểm tra có phạm vi khác nhau, không phải hai lần chạy cùng một nhóm ca.

Đã trực tiếp xem ảnh Drive sáng/tối, list/grid mobile, Move, quota ở viewport 390×360, Privacy có dữ liệu thật và upload hoàn tất. Ảnh là bằng chứng của những trạng thái đã chụp, không phải nghiệm thu mọi route.

## Các hành vi đã kiểm tra

| Nhóm | Bằng chứng browser |
|---|---|
| Chọn file | Space trên checkbox list; Space trên card grid; Star/menu con không mở hoặc chọn nhầm card |
| Modal | Native modal, nền inert, Tab không tới control nền; Escape; chặn đóng quota đang lưu; tiếp cận submit khi viewport thấp |
| Lỗi API | Bulk share, quota, plan và đổi role hiển thị lỗi trong modal; giữ email đã nhập; lọc quota lỗi không giữ dữ liệu cũ |
| Privacy | Lỗi Activity/Search có Retry, không báo thành công-rỗng; From/To độc lập và bao gồm ngày cuối |
| Điều hướng | Login/register giữ continuation lời mời; Settings hỗ trợ Back/Forward/refresh và drawer mobile |
| Theme/responsive | Light/dark theo lựa chọn lưu; Drive không tràn chiều ngang document ở hai viewport |
| Upload | Ẩn/mở lại upload đang Verifying; reduced motion vẫn có nhãn trạng thái; hoàn tất sau khi giải phóng response mô phỏng |
| Workspace | Request mang đúng workspace header, My Drive bỏ header; ép response A về sau B không ghi đè dữ liệu B |
| Admin | Đổi role cần xác nhận trước request; log details mở bằng Enter; lỗi tạo plan trong form |

32 ca mô phỏng chặn API trước backend; endpoint thiếu fixture làm test thất bại. Chúng chứng minh hành vi frontend trong điều kiện kiểm soát, không thay thế kiểm tra quyền/quota/email thật. Chrome có thể đưa Tab tới browser chrome; test modal không đánh đồng trường hợp đó với focus lọt vào ứng dụng phía sau.

6 ca thật dùng tài khoản thử thông thường, không chặn API:

- Session `/accounts/api/me/`, Drive items và Workspace discovery trả 200.
- Bốn section Settings render; endpoint me/quota/activity/search-history tương ứng trả 200 trước khi chụp ảnh.
- Upload mới 9 MiB qua hai part (8 MiB + 1 MiB), finalizer và trạng thái hoàn tất; download qua Django khớp từng byte với fixture.
- Chỉ file thử có tên duy nhất `ui-acceptance-<timestamp>.txt` và nội dung đã đối chiếu được chuyển vào Trash rồi xóa qua UI để trả quota. Không thay đổi file có sẵn, quyền thành viên, quota policy hoặc mật khẩu.

## Lỗi tìm thấy và xử lý

**Chia sẻ nhiều file:** lỗi API trước đây hiện ở toast sau native dialog. Đã thêm `shareError`, reset khi mở/lưu và render `role="alert"` trong `DriveShareDialog`. Ca browser thất bại trước sửa và đạt sau sửa trên cả hai viewport; email được giữ nguyên.

**Upload thật kẹt Verifying:** lượt đầu hết 180 giây. Đọc đúng session thử thấy job `pending`, `attempts = 0`. Đã chạy `run_upload_finalizer` có sẵn theo tài liệu dự án. Job đó chuyển sang `done`, attempts 1, session `available`; download được đối chiếu và fixture được dọn. Lượt upload mới sau đó đạt toàn bộ luồng trong khoảng 14 giây trên desktop và mobile. Không sửa cơ chế bảo mật/storage/backend để làm test đạt.

Worker local đã được khởi động trong phiên này và cần tiếp tục chạy để hoàn tất multipart. Lệnh chạy trong terminal riêng:

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py run_upload_finalizer
```

Shell agent kế thừa `DEBUG=release`, ghi đè `.env` local có `DEBUG=True`. Chỉ bỏ biến kế thừa trong tiến trình diagnostic/worker để dùng cấu hình dự án hiện có; không sửa `.env`, biến môi trường hệ thống hoặc cấu hình TLS.

TypeScript `--noEmit`, full ESLint, production build và `git diff --check` đạt sau sửa chia sẻ. Git chỉ cảnh báo LF/CRLF. Session, ảnh và HTML report được Git bỏ qua; trace/video tắt. Không ghi cookie, CSRF token hoặc URL ký vào báo cáo. Ảnh API thật có thể chứa tên tài khoản/file; giữ chúng riêng tư.

## Bổ sung nghiệm thu admin bằng phiên thật

Đã bổ sung `frontend/e2e/admin.spec.ts`: **33 kịch bản × 2 viewport = 66 ca admin**, gồm 27 route và 6 luồng tương tác/ranh giới truy cập. Chạy với session `admin.json`, tách khỏi `user.json`. Không mock response API; bộ ca xác nhận không phát sinh POST/PATCH/DELETE tới API quản trị.

**Lượt chốt 15:11–15:13 (UTC+7): 66/66 đạt, 0 skipped, 0 flaky, 0 unexpected; thời gian khoảng 125 giây.** Đây là 66 ca bổ sung cho bộ 38 ca trước, không cộng các lượt dò lỗi/chạy lại. Báo cáo HTML admin chứa ảnh đính kèm; báo cáo 38 ca trước vẫn được giữ tại đường dẫn cũ.

| Phạm vi | Route / hành vi và bằng chứng |
|---|---|
| Dashboard, danh sách | `/admin`, `/admin/users`, `/admin/organizations`, `/admin/workspaces`, `/admin/files`: access + API dữ liệu 200, heading đúng, không page crash/API lỗi, không tràn ngang document |
| Phân quyền, log, settings | `/admin/permissions`, `/admin/activity`, `/admin/audit`, `/admin/settings`: permissions/activity/audit/settings 200 và nội dung render |
| Health, quota | `/admin/infrastructure`; quota overview/users/workspaces/policies/capacity: overview, directory, plan, policy và hai audit-history endpoint 200 |
| Dịch vụ chưa nối | Security Alerts, Storage Topology; servers/storage/database/minio/alerts; backup overview/jobs/history/policies/restore: kiểm tra đăng nhập admin và trạng thái Unknown/unavailable/not connected đúng với implementation. Không chứng minh backup, restore, monitoring hoặc detection pipeline hoạt động |
| Giới hạn tài khoản | Admin chuyên dụng gọi Drive API bị 403 và UI Drive chuyển về admin. Tài khoản thường gọi access/users/quotas/permissions admin bị 403 và UI hiển thị Administrator access required |
| Tương tác chỉ đọc | Mở/đóng Sessions và GET sessions 200, không revoke; tìm tài khoản với query không khớp trả count 0; control quota phù hợp capability được server cấp, form chưa nhập lý do không cho lưu |
| Theme/điều hướng | Đổi light/dark, mở navigation mobile, tới Roles & Permissions, refresh giữ theme và Back về Dashboard |

Đã xem ảnh đại diện dashboard/settings desktop, user directory/settings/quota plans/sessions mobile và permissions dark. Các bảng rộng dùng vùng cuộn nội bộ; kiểm tra document không tràn ngang không đồng nghĩa mọi cột hiện đồng thời trên mobile. Ảnh admin có dữ liệu riêng tư, nằm trong thư mục Git bỏ qua. Ảnh được đính kèm báo cáo HTML ở lượt chốt.

Lượt đầu có ba assertion dùng sai nhãn chính xác (`Settings`, `Unknown` cho backup history/policies). Đối chiếu mã và nội dung render cho thấy nhãn thực là `System settings`, `Unknown records`, `Policy controls are unavailable.`; đã sửa test. Không sửa application source để đáp ứng những assertion sai đó. TypeScript và ESLint cho bộ ca mới đạt.

Kết quả admin được lưu riêng ở `frontend/test-results/admin-results.json` và `frontend/playwright-report/admin/index.html`, ảnh ở `frontend/test-results/admin/`. Hướng dẫn chạy: `npm run test:e2e:admin`; để mở báo cáo đã lưu, dùng `npx playwright show-report playwright-report/admin` từ frontend.

## Sửa lỗi cột thao tác Files theo ảnh người dùng

Ảnh người dùng cho thấy View/Trash xuống từng ký tự và MIME DOCX làm hàng giãn cao. Đã tái hiện bằng fixture có MIME dài, tên owner dài và cả file active/trash: ca browser thất bại trước sửa ở hai viewport.

Nguyên nhân là cột Actions chỉ rộng 8%, nút bị flex-shrink và kế thừa `overflow-wrap: anywhere` của bảng. Đã dùng chiều rộng cột cố định phù hợp, giữ minimum table 1120px hiện có, tái sử dụng nhóm `.rowActions` với button không co/ngắt chữ; nhóm có thể xuống dòng nguyên nút. MIME rút gọn bằng ellipsis với title đầy đủ, icon encrypted giữ riêng. Không thay đổi quyền hoặc handler thao tác.

Sau sửa: 2 ca regression với fixture và 4 ca API thật cho Files/Users đạt trên desktop/mobile. Đã xem ảnh thực tại desktop 1440px: View/Trash hiện trọn ngay trong bảng, MIME một dòng; fixture còn được chụp ở 1920px. TypeScript, ESLint file liên quan và diff whitespace check đạt. Không chạy lại toàn bộ bộ 38/66 ca cho thay đổi này; các báo cáo tổng hợp phía trên là bằng chứng của lượt trước. Ảnh mới nằm trong `frontend/test-results/file-layout/` và `frontend/test-results/file-layout-live/`.

## Thay đổi theo yêu cầu: bỏ Support, chuyển timeline về Workspace Activity log

- Bỏ mục Support trong menu tài khoản, Settings, đăng nhập và Plan details; gỡ route `/account/support` và helper cấu hình URL không còn người dùng. Route cũ trả 404. Thông báo upload không còn hướng người dùng tới Support đã gỡ.
- Recent cá nhân và Recent Workspace chỉ còn danh sách file. Giữ nguyên biểu đồ 14 ngày theo lần truy cập/cập nhật file gần nhất, chuyển sang `/drive/workspaces/[workspaceId]/activity`; tên điều hướng là Activity log. Biểu đồ đọc đúng workspace qua request scope tường minh, chỉ tải sau khi API activity cho phép truy cập.
- Biểu đồ lỗi không che nhật ký; Refresh tải lại cả hai. API activity từ chối thì không tải hoặc hiển thị biểu đồ. Cơ chế phân quyền backend được giữ nguyên.
- Khi xem ảnh mobile đã phát hiện min-width bên trong biểu đồ làm viewport mở rộng từ 390 lên khoảng 594px dù body vẫn 390px. Thêm containing block `relative` cho vùng cuộn biểu đồ đã khắc phục. Test hiện so sánh chiều rộng document/body với viewport kiểm thử thực, không dùng `innerWidth` đã bị mở rộng; xác nhận cuộn tới ngày cuối trong biểu đồ.

Kiểm tra: 42 ca mô phỏng đạt trước lượt siết kiểm tra chiều rộng; sau sửa cuối, chạy lại 8 ca Support/timeline và đều đạt ở desktop/mobile. 4 ca API thật chỉ đọc cho Drive/Settings, kiểm tra Recent thật riêng, 2 unit test lịch ngày, TypeScript, ESLint và production build đạt. HTTP smoke cập nhật đạt 51 route delivery, 5 HTTP + 1 streamed redirect, 4 HTTP + 3 streamed not-found và 2 continuation check. Workspace Activity mới được kiểm tra bằng fixture API; chưa khẳng định nghiệm thu lại luồng Workspace thật có quyền quản lý trong lượt này.

Đã xem ảnh Recent thật và Workspace Activity log desktop/mobile. Ảnh sau sửa cuối ở `frontend/test-results/support-timeline-final/`; ảnh Recent thật ở `frontend/test-results/support-timeline-live/personal-recent.png`. Các báo cáo 38/66 ca phía trên là bằng chứng lịch sử, không phải số lượt chạy đầy đủ sau yêu cầu mới này.

## Giới hạn hiện tại

- Đã kiểm tra API đọc admin bằng tài khoản có quyền thật. Luồng ghi thật như đổi quyền/thành viên, suspend/revoke, đổi quota/plan/settings chưa được thực hiện; test mô phỏng không thay thế phần này.
- Không thử thay đổi quyền, quota policy, mật khẩu, gửi email hoặc tạo tài khoản mới.
- Chưa nghiệm thu mọi route trong inventory ban đầu, screen reader, thiết bị cảm ứng thật, browser zoom 200%, profiling folder lớn hoặc flash ở first paint. Mobile emulation và screenshot theme không chứng minh những tiêu chí đó.
- Không nâng điểm UX 21/40 chỉ dựa vào số test đạt. Audit ban đầu vẫn là baseline source-only.

Chạy lại theo [frontend/e2e/README.md](../frontend/e2e/README.md). Quy trình đăng nhập thủ công → fixture lỗi/race → API thật → xem ảnh → ghi giới hạn có thể đóng gói thành Agent Skill dùng lại.

---

## Hồ sơ kết nối trước khi dùng Playwright (lịch sử)

Toàn bộ các mục bên dưới ghi trạng thái **trước** lượt Playwright, không phải giới hạn hiện tại.

Target supplied by the user: `http://localhost:3000/drive`, in Google Chrome.

## Current evidence

- Direct browser connection to the supplied URL returned `The browser access host is unavailable`.
- Earlier native Chrome inspection identified the BlueDrive window but stopped before reading the page because the tool could not confidently verify its current URL. Providing a URL does not establish a working browser-control connection.
- Frontend is now running: Drive responds HTTP 200.
- The existing HTTP smoke suite passed again against the user's running `http://localhost:3000`: 52 route deliveries, 5 HTTP redirects plus 1 streamed redirect, 3 HTTP 404s plus 3 streamed not-found boundaries, and both invitation-continuation assertions.
- The configured public frontend API origin is `http://localhost:8000`.
- Read-only API prerequisites passed for the browser origin `http://localhost:3000`: CSRF endpoint 200 with a token present; exact credentialed CORS origin; login OPTIONS preflight 200 with the CSRF header allowed. An unauthenticated `/accounts/api/me/` request returned 403. Token/cookie values were not logged or persisted.

These are availability and HTTP/CORS checks. They are **not** evidence of browser rendering, a successful authenticated session, real uploads, permissions changes or quota mutations.

## Connection handoff

The official browser-extension setup requires the desktop app's Settings → Computer Use → Google Chrome to show Manage, with the ChatGPT extension connected in the active Chrome profile. The user has been asked to report that connection state. No browser permissions or application settings were changed by this agent.

Official source: [ChatGPT browser extension setup and troubleshooting](https://learn.chatgpt.com/docs/chrome-extension).

## Acceptance still pending

1. Observe the actual signed-in Drive page and confirm account/workspace scope.
2. Check list/grid selection and child action buttons with keyboard input.
3. Exercise upload hide/reopen and success/retry with a clearly identified test file.
4. Inspect native dialogs for focus, Escape, pending-state guards and visible API errors.
5. Check Settings URL/Back, date filters, both themes, short/mobile viewports and zoom.
6. Exercise workspace/admin views using the necessary existing account roles. Permission, quota, credential and destructive mutations require an appropriate test context and any applicable action confirmation.

No acceptance item above is marked complete based on the HTTP checks. The current blocker is the browser-control bridge, not application availability.
