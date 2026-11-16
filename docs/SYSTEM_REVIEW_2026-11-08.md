# BlueDrive — Báo cáo rà soát và sửa lỗi hệ thống

Ngày: 08/11/2026 · Môi trường: Windows local, PostgreSQL, Django, Next.js, Chrome và MinIO.

## Kết quả và phạm vi

Đã kiểm kê hệ thống hiện tại, sửa trực tiếp các lỗi xác nhận được và kiểm tra lại theo từng nhóm nghiệp vụ. Trọng tâm là tính đúng đắn của cộng tác Workspace, vòng đời file, quota, tải lên/tải xuống, phản hồi khi lỗi, bàn phím và các màn hình quản trị. Những thay đổi có sẵn trong working tree được giữ nguyên; báo cáo này phân biệt bản sửa của lượt rà soát với tính năng đã triển khai từ trước.

Kết quả cuối: **405 ca backend, 396 đạt và 9 bỏ qua có chủ đích; 152 unit frontend đạt; 156 ca browser hồi quy đạt; 5 ca API/MinIO thật đạt; 8 ca điều hướng được kiểm tra lại sau tinh chỉnh cuối đạt.** TypeScript, lint, production build và Django checks đều đạt. Các dịch vụ chưa triển khai đầy đủ được liệt kê riêng ở cuối, không được coi là đã hoàn thiện chỉ vì giao diện tải được.

Kiểm kê hiện tại gồm **41 page entry point, 68 React component TSX và 143 file Python ngoài migrations**. Kiểm kê không có nghĩa mọi dòng mã hoặc mọi tổ hợp dữ liệu đã được đọc/thử thủ công. Phạm vi bằng chứng gồm đọc mã các luồng trọng yếu, test backend toàn bộ các app nghiệp vụ, unit test frontend, Chrome desktop/mobile, API có đăng nhập và các fixture MinIO thật.

Skill đã dùng: **ponytail** để giữ thay đổi tối thiểu, tái sử dụng mẫu sẵn có; **impeccable** với quy trình audit/critique/harden và kiểm tra màu, responsive, trạng thái lỗi. Hai đánh giá giao diện được thực hiện độc lập, không đọc kết quả của nhau: A đánh giá UX; B đánh giá kỹ thuật, detector và trình duyệt. Không dùng skill tạo ảnh, slide hay bảng tính vì không phục vụ việc sửa ứng dụng này.

### Ma trận chức năng

| Nhóm | Phạm vi kiểm tra | Loại bằng chứng |
|---|---|---|
| Tài khoản, đăng nhập, lời mời | Session/CSRF, continuation đăng ký, thay email, bảo vệ thao tác nhạy cảm, trạng thái không tải được tài khoản | Backend, frontend unit, browser mock; trang tài khoản thật chỉ đọc |
| My Drive | Danh sách/lưới, tìm kiếm, sort, chọn nhiều, mở bằng bàn phím, rename/move/duplicate, starred, thùng rác, lỗi/rỗng | Backend, browser mock và browser đăng nhập |
| Workspace | Giới hạn tenant/workspace, Editor/Viewer, thư mục có nhiều người tạo, thành viên, hoạt động, archive/restore | Backend; browser mock cho thay quyền/archive; upload/quota thật bằng fixture riêng |
| Upload và quota | Multipart, hoàn tất qua worker, reservation, vượt quota, abort, chỉ tính đúng Workspace, quota cá nhân không đổi | Backend và Chrome → API → MinIO thật |
| Download/preview | Cấp quyền, presigned GET, legacy download, ZIP, lỗi storage, không forward cookie, VersionId | Backend, browser mock và native download MinIO thật |
| Chia sẻ | Quyền xem/sửa, direct share, thao tác lặp không tạo log thừa, lỗi trong modal, giữ nguồn thư mục chia sẻ | Backend, browser mock; không gửi lời mời/email thật trong lượt này |
| Quản trị | Users, Organizations, Workspaces, Files, Permissions, Activity/Audit, Settings, Quotas; quyền admin và trạng thái dịch vụ chưa kết nối | API admin thật chỉ đọc, desktop/mobile; lỗi mutation dùng mock |
| Cấu trúc/cấu hình | Phân lớp route/component/service, helper cây thư mục, migration, dependency đã cài, template môi trường, README/ADR/API docs | Đọc mã, Django checks, migration check, pip check, TypeScript, lint, build |

## Các bản sửa và lý do

### A. Nghiệp vụ và dữ liệu

| ID | Lỗi trước khi sửa | Thay đổi và lý do | File chính |
|---|---|---|---|
| B01 | Editor được cấp quyền Workspace nhưng không di chuyển được file vào thư mục của đồng nghiệp vì truy vấn đích vẫn lọc `owner=request.user` | Dùng tenant + Workspace + kiểm tra quyền sửa đích. Người tạo không còn bị dùng thay cho quyền cộng tác | `backend/dashboard/drive_api.py` |
| B02 | Trash/restore/delete cây thư mục chỉ xử lý một phần tệp/thư mục của người thực hiện; có thể báo thành công nhưng bỏ sót nội dung của đồng nghiệp | Duyệt toàn bộ cây trong cùng tenant/Workspace và xử lý mọi người tạo sau khi đã kiểm tra quyền. Đồng bộ cả API mới, vòng đời thư mục legacy và legacy bulk trash | `backend/dashboard/drive_api.py`, `backend/dashboard/views.py`, `backend/folders/views.py` |
| B03 | Duplicate thư mục bỏ sót nội dung của người tạo khác; duplicate file trong thư mục của đồng nghiệp có thể lỗi 500 sau khi đã publish | Duyệt đủ cây và tra file sau finalize bằng ID + tenant + Workspace. Giữ quy tắc ownership hiện có của finalizer thay vì giả định chủ file luôn là người bấm Duplicate | `backend/dashboard/drive_api.py` |
| B04 | Tên upload/copy kiểm tra trùng theo owner trong khi ràng buộc database là theo Workspace và vị trí; tên khác hoa/thường hoặc tên copy dài có thể gây lỗi | Kiểm tra tên live không phân biệt hoa/thường trên cùng Workspace/cha; giới hạn tên tự sinh theo độ dài cột, chừa chỗ cho hậu tố copy/số thứ tự. Tên đã vào Trash có thể được tái sử dụng theo ràng buộc hiện tại | `backend/files/services.py`, `backend/dashboard/views.py` |
| B05 | Folder details đếm thiếu số thư mục/file do chỉ tính cùng owner | Đếm toàn bộ nội dung live thuộc cây Workspace đã được phép xem | `backend/folders/views.py` |
| B06 | Hai thao tác khôi phục đồng thời có thể gặp tên vừa xuất hiện sau bước kiểm tra và trả lỗi 500 | Bắt `IntegrityError` bên ngoài transaction; rollback cả cây và trả 409 với hướng xử lý rõ. Có test ép xung đột ở bước cập nhật file để kiểm tra thư mục không bị khôi phục dở dang | `backend/dashboard/drive_api.py` |
| B07 | Template database vẫn gợi ý cổng MySQL 3306 dù settings đã dùng PostgreSQL 5432 | Đồng bộ cổng 5432 và username mẫu `securedrive_app`; không sửa thông tin kết nối thật | `backend/.env.example` |

**Vì sao chọn cách này:** Workspace giống một phòng làm việc chung: quyền vào phòng quyết định ai được sắp xếp tài liệu, không phải tên người đặt từng tờ giấy lên kệ. Bản sửa bỏ bộ lọc người tạo ở đúng các truy vấn cộng tác, đồng thời giữ ranh giới tenant/Workspace và quyền do backend quyết định.

Tách phép duyệt cây vào **`backend/folders/tree_service.py`** để các luồng dùng cùng một cách giới hạn scope, nhận biết bản ghi đã duyệt và tránh vòng lặp. Giữ interface `_owned_subtree` cho các caller legacy cần scope owner; không đổi framework hay viết lại toàn bộ module. Test mới nằm trong **`backend/dashboard/test_workspace_collaboration.py`**.

### B. Giao diện và trải nghiệm

| ID | Hành vi gây khó chịu | Bản sửa | File chính |
|---|---|---|---|
| U01 | Mất mạng khi kiểm tra admin bị trình bày thành không có quyền, chỉ còn link đăng nhập | Phân biệt lỗi kết nối/dịch vụ với 401/403; thêm Retry cho account load và admin access check. Không mở nội dung quản trị khi chưa xác minh quyền | `AccountProvider.tsx`, `AdminConsole.tsx` |
| U02 | Bấm lại tab All files/Users đang active hoặc tìm lại cùng query có thể tải vô hạn vì không có dependency nào đổi để fetch | Dùng revision refresh sẵn có, bảo đảm thao tác chuyển sang loading luôn gắn với một request thực | `AdminFileDirectory.tsx`, `UserDirectory.tsx` |
| U03 | Sửa email khi đang lưu mở lại nút Save; hai phản hồi ngược thứ tự làm input hiện email cũ nhưng báo thành công | Khóa các trường đã gửi khi đang lưu và chặn submit kép bằng pending guard riêng. Sau lỗi vẫn có thể sửa/thử lại | `AccountProfilePanel.tsx` |
| U04 | Clear search xóa bộ lọc nhưng để nguyên chữ trong header | Header nghe cùng sự kiện thay đổi query với Drive; test cả Clear và Back sau khi URL đã commit | `Header.tsx` |
| U05 | Mở thư mục được chia sẻ làm mất nguồn chia sẻ, breadcrumb và sidebar lại chỉ My Drive | Hiện Shared with me, tên người chia sẻ, quyền truy cập và đường quay lại; sidebar lấy ngữ cảnh từ folder details đã tải, không đoán ownership từ URL | `DriveFileBrowser.tsx`, `DashboardShell.tsx`, `Sidebar.tsx`, `DriveFolderNavigation.tsx`, `SharedFolderContext.tsx` |
| U06 | Tên file/thư mục trong list không focus được để Enter mở; handle kéo thả chiếm Tab dù không có thao tác bàn phím | Tên thành button có tên truy cập Open; checkbox tiếp tục dùng để chọn; bỏ drag handle khỏi Tab order. Click tên mở nội dung, các vùng chọn và menu vẫn tách biệt | `browser/DriveListTable.tsx` |
| U07 | Drive rỗng trên điện thoại không có hành động bắt đầu thấy được; Viewer vẫn được mời tạo nội dung Workspace | Thêm Upload files ngay trong empty state tại nơi có quyền ghi. Dùng lại dữ liệu Workspace từ switcher để hiện CTA/New cho Editor/admin, ẩn với Viewer; picker đi qua luồng chụp destination hiện có | `DriveFileBrowser.tsx`, `DriveNewMenu.tsx`, `SelectedWorkspaceContext.tsx`, `DashboardShell.tsx` |
| U08 | Lỗi archive/restore Workspace nằm sau hộp thoại đang mở | Truyền lỗi vào `ConfirmDialog`, xóa lỗi cũ khi mở/đóng và tránh lặp lỗi ở nền | `OrganizationAdminPage.tsx` |
| U09 | Placeholder search ở light mode chỉ đạt khoảng 3,4:1 | Dùng token `--muted` với opacity 1 cho input/textarea; kiểm tra lại cả light/dark | `app/globals.css` |
| U10 | Drive tải lỗi chỉ đổi nội dung trực quan, không có thông báo trong live region | EmptyState hỗ trợ role; riêng nhánh tải lỗi dùng alert, không biến mọi trạng thái rỗng thành cảnh báo | `shared/EmptyState.tsx`, `DriveFileBrowser.tsx` |
| U11 | Toast thông tin/thành công thông thường mặc định mang sắc thái warning | Đổi nhánh thông báo chung sang info, giữ các nhánh lỗi đã nhận biết | `DriveFileBrowser.tsx` |
| U12 | Menu dùng frame sau để trả focus, có thể kéo focus khỏi thẻ vừa được người dùng chọn bằng bàn phím | Trả focus về trigger ngay khi đóng; test Escape, focus trigger, sau đó Space chọn card trên desktop/mobile | `ui/ContextMenu.tsx`, `e2e/mocked.spec.ts` |

Các thay đổi dùng Button, ConfirmDialog, token màu và API client hiện có. Không thêm dependency. Giống một bộ biển chỉ đường: cùng một nơi phải có cùng tên trên biển cửa, bản đồ và nút quay lại; lỗi mạng phải chỉ cách thử lại, không kết luận nhầm rằng người dùng mất quyền.

Các file mới phục vụ điều phối UI nằm cạnh nghiệp vụ tương ứng: `SelectedWorkspaceContext.tsx` ở `components/workspaces/`, `SharedFolderContext.tsx` ở `components/drive/browser/`. Backend vẫn là nơi quyết định quyền; ẩn nút trên UI không thay cho kiểm tra quyền API.

### C. Công cụ và tài liệu

- ESLint bỏ qua `test-results/`, `playwright-report/` và auth state. Các script khảo sát tạm trong artifact không bị coi là source ứng dụng; code và test e2e chính vẫn được lint. Không xóa bằng chứng chỉ để làm lint xanh.
- README gốc, backend README, frontend README, ADR-0001, API contract và data model được đánh dấu/sửa phần mô tả cũ. Các tài liệu trước đó còn khẳng định chưa có S3 adapter, chưa có upload session, thiếu lockfile, hoặc mọi file publish đều AES-encrypted và mọi download đi qua Django.
- Trạng thái đúng hiện tại: multipart mới được xác minh và publish thành S3 object **không mã hóa AES ở tầng ứng dụng**; provider SSE là cấu hình riêng. Legacy AES vẫn cần khóa gốc. `SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED` bật presigned GET cho file đủ điều kiện; encrypted legacy, preview và ZIP vẫn qua Django.
- Tài liệu thiết kế lịch sử được giữ lại và có chú thích rõ, không bị sửa thành bằng chứng nghiệm thu cho tính năng hiện tại. Giống sổ thiết kế và biên bản bàn giao: bản vẽ cũ hữu ích, nhưng không thể dùng nó để khẳng định thiết bị hiện đang lắp trong nhà.

## Kiểm chứng

| Kiểm tra backend | Kết quả cuối |
|---|---|
| Toàn bộ accounts, dashboard, files, folders, sharing, security, logs | 405 ca trong 548,8 giây; **396 đạt, 9 skipped, 0 lỗi** |
| Nhóm tập trung cộng tác/tree/legacy/ZIP/permission | 58/58 đạt |
| 9 ca MinIO tích hợp tùy chọn | Không chạy vì yêu cầu môi trường/bucket tích hợp riêng; thay vào đó đã nghiệm thu các luồng MinIO thật bằng fixture được cô lập trong 5 ca browser live |

Các dòng 403/409/413/503 và cảnh báo storage trong test log có thể là tình huống lỗi được test chủ động tạo ra. Kết luận cuối lấy từ runner `OK (skipped=9)`, không dựa vào việc log hoàn toàn không có chữ warning.

| Kiểm tra frontend và môi trường | Kết quả cuối |
|---|---|
| Frontend unit | 152/152 đạt |
| Browser hồi quy `mocked`, `download`, `admin`, `system-review` | 156/156 đạt, không retry tự động |
| Kiểm tra lại điều hướng sau tinh chỉnh sidebar cuối | 8/8 đạt trên desktop/mobile |
| API/MinIO thật: tài khoản, settings, multipart cá nhân, native download, Workspace quota | 5/5 đạt |
| TypeScript, ESLint, production build | Đều đạt trên bản frontend cuối |
| Django system check | Không phát hiện vấn đề |
| Migration check | Không có model change thiếu migration |
| Dependency Python đã cài | `pip check`: không có dependency hỏng |
| Kiểm tra whitespace diff | Đạt; Git chỉ nhắc quy tắc chuyển LF/CRLF trên Windows |

Browser hồi quy giữ được các chỉnh sửa đã có: không còn Support trên UI người dùng; Recent không có timeline, timeline nằm trong Activity log của Workspace; bảng admin giữ MIME dài gọn và nút thao tác không vỡ chữ; modal/keyboard/upload tray và lỗi quota tiếp tục hoạt động. Các class Tailwind cũ được nêu ở `WorkspaceMembersPage.tsx` không còn trong file hiện tại.

Luồng native MinIO dùng file 16 MiB: sau khi API cấp URL, test ghi thêm phiên bản khác của cùng object; URL vẫn tải đúng bytes/SHA-256 của phiên bản đã cấp. Request storage không mang cookie/header ứng dụng; truy cập không chữ ký bị từ chối; cleanup kiểm tra không còn version/delete marker của fixture. Lượt cuối dùng TTL local thông thường, **không chờ hết TTL để chứng minh expiry lần nữa**; kiểm tra TTL ngắn trước đó được ghi riêng trong báo cáo download.

### Quy trình bắt lỗi và kiểm tra lại

Nhóm cộng tác ban đầu có 9 test hồi quy mới: **6 fail, 1 error, 2 pass** trước bản sửa. Sau sửa, nhóm 39 test liên quan đạt; nhóm mở rộng 58 test bao gồm tree helper, legacy, ZIP và permission boundaries cũng đạt. File test cộng tác cuối có 13 trường hợp, gồm Viewer bị từ chối, đích khác Workspace, nhiều người tạo, giới hạn tên và rollback khi xung đột.

Bộ backend toàn diện giữa lượt bắt được một regression thiếu tham số `owner` trong lời gọi chia sẻ. Đã sửa và chạy lại toàn bộ; không xem lần chạy có lỗi là kết quả đạt. Lượt browser giữa quá trình có một request tài khoản bị gián đoạn lúc Django autoreload và một lỗi focus menu; focus được sửa, các suite được chạy lại khi mã ổn định.

### Loại bằng chứng và giới hạn

- Chrome chạy qua Playwright, desktop 1440×900 và mobile emulation 390×844. Đã xem ảnh sau sửa của các trạng thái đại diện. Đây là trình duyệt thật với mobile giả lập, không phải chứng nhận trên điện thoại vật lý.
- Admin thật được kiểm tra chỉ đọc. Các lỗi PATCH profile/archive/role/quota dùng response mock, không thay email, mật khẩu, quyền hay chính sách quota của tài khoản thật.
- Test MinIO thật chỉ dùng tên fixture tạo riêng, xác minh nội dung tải xuống rồi dọn đúng file; Workspace fixture được archive sau khi used/reserved quota về 0. Log kiểm thử không xuất credential, cookie hay presigned URL.
- Detector source của đánh giá B chạy thành công trên 171 file tại thời điểm đánh giá trước sửa, exit 0, JSON `[]`. Overlay runtime trên bốn trang tìm được hai placeholder contrast thật. Một text-occlusion là nhãn do overlay tự chèn, được loại là false positive. Scan sạch không phủ định các lỗi phát hiện qua nghiệp vụ/bàn phím.
- Overlay chạy trong Chrome headless, không có tab Human nhìn thấy được. Server overlay port 8400 đã dừng; API, frontend và worker local được giữ hoạt động. Worker được khởi động lại khi không có upload đang finalize để nạp helper tên file mới.

## Đánh giá UX trước sửa

Đây là điểm của hai đánh giá độc lập ở đầu lượt, **không phải điểm nghiệm thu sau sửa** và không dùng để khẳng định toàn hệ thống hết lỗi.

| Nielsen heuristic | /4 |
|---|---:|
| Hiển thị trạng thái hệ thống | 2 |
| Khớp cách hiểu thực tế | 3 |
| Quyền kiểm soát và thoát | 3 |
| Nhất quán | 3 |
| Ngăn lỗi | 3 |
| Nhận biết thay vì ghi nhớ | 2 |
| Hiệu quả thao tác | 2 |
| Tối giản/thẩm mỹ | 3 |
| Nhận biết và phục hồi lỗi | 2 |
| Hướng dẫn/trợ giúp ngữ cảnh | 1 |
| **Tổng UX** | **24/40** |

Kỹ thuật trước sửa: accessibility 2, performance 3, theming 3, responsive 3, implementation integrity 2 — **13/20**, đánh giá tạm tính. Performance chưa có trace tải lớn; responsive chưa có nghiệm thu native browser zoom.

Nên giữ: hệ token light/dark, dialog dùng chung, URL Workspace rõ, xác nhận phá hủy, quota reservation và chụp đích upload trước tác vụ bất đồng bộ. Giao diện phù hợp ứng dụng quản lý tệp tập trung vào tác vụ; không có lý do thay thương hiệu hay thêm hiệu ứng trang trí trong lượt này.

Tải nhận thức còn nằm ở toolbar nhiều icon và các khu quản trị dày dữ liệu. Người dùng mới hưởng lợi từ CTA ở Drive rỗng; người dùng bàn phím có đường mở trực tiếp; người quản trị không còn phải đoán lỗi mạng là lỗi quyền. Màn hình quản trị rộng vẫn có bảng cuộn ngang bên trong trên mobile, không biến thành cuộn ngang toàn trang.

## Những phần vẫn chưa thể gọi là hoàn thiện toàn hệ thống

| Phần | Trạng thái thực tế / giới hạn |
|---|---|
| Backup jobs, policies, history và restore | UI nói rõ dịch vụ chưa kết nối; không có bằng chứng sao lưu/phục hồi vận hành end-to-end |
| Security Alerts và telemetry topology/hạ tầng vật lý | Chưa có pipeline dữ liệu thật cho các màn hình này; không coi empty state là một hệ thống giám sát đã chạy |
| Nâng gói cá nhân / billing | Chưa kết nối quy trình nâng gói; UI hiện trạng thái chưa khả dụng |
| Mã hóa/scan cho multipart mới | Không có AES ứng dụng cho file mới; private bucket không chứng minh SSE đã bật. Scanner không được cấu hình không đồng nghĩa đã quét mã độc |
| Hạ tầng production | Lượt này kiểm tra local; chưa nghiệm thu HTTPS, rotation/recovery khóa, giám sát worker/cleanup, backup restore và vận hành production |
| Accessibility nâng cao | Chưa chạy NVDA/VoiceOver, chưa kiểm tra điện thoại thật. Stress 320px + cỡ chữ 200% có overflow nội bộ ở một số form/filter; chưa tương đương native browser zoom |
| Quy mô lớn | Chưa profile folder hàng chục nghìn mục, load test đồng thời hoặc đo hiệu năng bundle production |
| Các luồng thật gây thay đổi tài khoản | Không gửi email, đổi mật khẩu, đổi role hay dữ liệu tổ chức thật; các nhánh này có unit/integration/mock browser thay cho nghiệm thu trên dữ liệu thật |
| Legacy UI | Đã sửa vòng đời cây thư mục/bulk trash liên quan; không chứng nhận toàn bộ giao diện Django cũ trên mọi tổ hợp copy/cut/paste. Next.js là giao diện chính |

Không có lỗi P0 nào được xác nhận trong phạm vi đã chạy; điều này không phải cam kết không tồn tại lỗi nghiêm trọng khác. Các mục chưa kết nối ở trên là phần triển khai còn thiếu, không được che bằng dữ liệu giả hoặc báo thành công giả.

## Bằng chứng có thể xem lại

Trong repository `C:\Users\dang2\Project\SecureDrive`:

- `backend/dashboard/test_workspace_collaboration.py`: 13 test cộng tác và lỗi hồi quy mới.
- `frontend/e2e/system-review.spec.ts`: 14 kịch bản mới, chạy desktop/mobile thành 28 ca.
- `frontend/test-results/system-backend-final.txt`: kết quả backend cuối.
- `frontend/test-results/system-backend-targeted.txt`: 58 test liên quan.
- `frontend/test-results/system-unit-results.txt`: unit frontend.
- `frontend/test-results/system-verified-results.json`, `frontend/playwright-report/system-verified/`: hồi quy browser.
- `frontend/test-results/system-navigation-results.json`, `frontend/test-results/system-navigation/`: kiểm tra lại sidebar/ngữ cảnh chia sẻ sau tinh chỉnh cuối.
- `frontend/test-results/system-live-results.json`, `frontend/test-results/system-live/`: upload, quota, download MinIO thật.
- `frontend/test-results/system-review-a/`, `frontend/test-results/system-review-b/`: ảnh, phép đo và assessment độc lập trước sửa.

Các artifact/auth state được giữ ngoài source tracking. Không commit hay xóa thay đổi cũ của người dùng trong lượt này.

## Quy trình tái sử dụng

Có thể đóng gói quy trình **kiểm kê → hai đánh giá độc lập → test tái hiện → sửa nhỏ nhất → kiểm thử lại → nghiệm thu fixture thật → báo cáo bằng chứng/giới hạn** thành một Agent Skill riêng cho BlueDrive. Skill đó nên quy định database test riêng, media/email cô lập, fixture có tiền tố rõ, không xuất URL ký/credential và phân biệt nguồn mô phỏng với API/storage thật.

Questions skipped: user requested autonomous execution.
