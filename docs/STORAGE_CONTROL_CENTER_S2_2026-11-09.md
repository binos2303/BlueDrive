# BlueDrive Storage Control Center — Kết quả S2

Ngày: 09/11/2026. Nhánh: `feature/storage-control-center-s2-20261108`.

## Kết quả bàn giao

Đã triển khai Connect Existing, giao diện dùng chung Platform/Organization, đích storage bất biến cho upload/file và phục hồi mẫu kiểm tra LAB. Mã đã đưa vào workspace thật sau kiểm thử cô lập. Schema local đã cập nhật sau backup; không backfill hay di chuyển object cũ. `.env` không bị sửa, mọi cờ storage vẫn OFF.

**Kiểm chứng cuối: 532 bài backend, 523 PASS, 9 MinIO integration SKIP, không FAIL.** Có 35 bài mới so với mốc S1 497. A01 và A02 của bộ kiểm chứng nguyên bản đều đạt khi chạy riêng năm lần. Frontend đạt TypeScript, lint toàn bộ, build production và kiểm thử Chrome desktop/mobile. **G2 chưa đóng:** chưa có nghiệm thu với một cluster MinIO LAB thật đã chốt edition/license/identity/policy.

Giống lắp bộ chuyển kho: mã và các chốt an toàn đã được thử, nhưng chưa chuyển hàng thật sang kho mới trước khi kho đó được nghiệm thu.

## Những gì đã sửa và lý do

| Nhóm file | Thay đổi | Vì sao |
|---|---|---|
| `infrastructure/models.py`, migration0003/0004; `files/models.py`, files0017 | Connection revision, probe receipt, Platform default và pin trên upload/location; FK/trigger bảo vệ ownership, version, publication | Đổi binding không làm request/worker/file cũ âm thầm chọn kho mới |
| `infrastructure/connection_profiles.py` | Profile server-side theo scope, CIDR/DNS validation, HTTPS/CA, socket pinning, tắt proxy, chặn redirect origin | Browser không chỉ định endpoint/secret tùy ý; DNS không đổi đích socket sau kiểm tra |
| `infrastructure/connections.py`, `connection_api.py`, `urls.py` | Register idempotent, read check có lease/generation, binding có expected generation và audit | Có thể retry sau gián đoạn, chống ghi đè cấu hình mới từ màn hình cũ |
| `infrastructure/connection_probes.py`, cleanup command | Tạo bucket tạm UUID, sample64 bytes/version/SHA/SSE receipt, browser proof, cleanup có ownership và generation | HEAD không đủ chứng minh luồng browser; dọn dẹp lỗi phải giữ pending và chặn bind |
| `files/storage_routing.py`, factory, S3 adapter | Adapter theo revision được ghim; public signer cho multipart; legacy NULL giữ factory cũ | Upload mới/cũ, read và cleanup đến đúng kho; không phụ thuộc binding hiện tại |
| `files/upload_api.py` | Serialize/reload lúc initialize; GET status chỉ đọc; complete kiểm tra lại state; abort không lỗi khi chưa có reservation | Sửa A02 tạo nhiều multipart và A01 GET gây side effect; phục hồi session bị ngắt trước giữ quota |
| Finalization/worker/cleanup, `files/views.py`, duplicate/permanent-delete helpers | Publication/location cùng pin, đọc/copy/dọn đúng target; cleanup kiểm tra state/location trước xóa | Giữ đúng quota/dữ liệu khi đổi revision; không cho legacy HTML upload bypass routing |
| `components/storage/*`, storage service, hai route, Sidebar/AdminConsole | Profile chooser, read/LAB check, explicit confirmation, retry/reload, prepared binding và trạng thái routing off | Người dùng biết bước nào đã đạt, bước nào còn thiếu và có đường phục hồi lỗi |
| Backend tests, `e2e/storage-connections.spec.ts`, mock capabilities | Thử quyền, CSRF, TLS, network, cleanup, pinning, quota, Platform/Org isolation và giao diện | Có bằng chứng hành vi; flag-off không làm các trang cũ gọi API không hỗ trợ |
| ADR-0003, runbook, API/data model/progress | Đồng bộ contract, rollout, giới hạn và rollback | Tránh vận hành theo trạng thái S1 hoặc hiểu LAB verified là production-ready |

Danh sách file và SHA-256 hiện hành nằm trong `source-changes.json` của bộ evidence. Đây là danh sách phạm vi S2, không coi toàn bộ dirty Git diff của dự án là thay đổi lượt này. Không reset/stash/commit hoặc tạo PR.

## Hành vi nghiệp vụ đã kiểm tra

Upload A giữ connection A sau khi đổi default sang revision B; authorize part, publication, location, read và cleanup của A vẫn dùng A. Upload mới dùng B. Quota Workspace tăng reserved/used đúng một lần, không chuyển chi phí sang quota cá nhân. Thiếu business binding hoặc diagnostic storage lỗi thì upload mới dừng trước khi giữ quota/gọi provider. Business không rơi về Platform default; personal tenant dùng Platform default khi routing được bật trong fixture.

Connection/target cũ không bị sửa khi operator thay profile registry. DB từ chối đổi pin hoặc publication không có available location cùng connection/config. Tắt routing vẫn giữ reader biết revision; legacy rows vẫn có cơ chế cũ. Không tự chuyển file cũ hoặc copy dữ liệu giữa cluster.

Profile chỉ được chọn theo quyền/scope. Org khác, Platform role vào Org và viewer không thể điều khiển connection/probe. Mutations cần session CSRF. Expected generation sai bị conflict; replay cùng target là no-op. Đọc bucket thành công chỉ là read_verified, chưa được bind. Không cấp quyền hạ tầng chỉ vì có quyền quản lý file/Workspace.

LAB proof không thay policy data bucket. Mẫu kiểm tra dùng bucket mới, version thật trong S3 fixture, digest ngẫu nhiên; browser tính digest từ bytes đã đọc. Sai digest/expiry không đạt; lỗi cleanup không đánh dấu ready. Object lạ còn nguyên và khiến DeleteBucket thất bại. Reload tìm lại pending probe, retry browser/cleanup tiếp tục được. Stale cleanup completion không ghi đè generation mới.

Transport đã được thử với TLS server tạm thật trên loopback: CA/SNI đúng thành công; CA không tin cậy và hostname sai bị chặn. Các bài mock socket kiểm tra metadata/link-local, mixed DNS, redirect khác origin, không proxy và đóng client khi DNS bị từ chối. TLS/credential/timeout được phân loại lỗi riêng, không trả raw SDK message.

## Kiểm chứng và giới hạn bằng chứng

| Kiểm tra | Kết quả | Evidence |
|---|---|---|
| Full backend discovery từ source đã publish | 532 bài; 523 PASS, 9 SKIP; 51,5s | `backend-release.txt`, `backend-isolation.json` |
| A01 nguyên bản, lặp riêng | 5/5 PASS | `a01-repeat.txt` |
| A02 nguyên bản, hai DB connection, lặp riêng | 5/5 PASS | `a02-repeat.txt` |
| Chrome regression + S2 lần đầu | 52/52 PASS: 44 bài cũ +8 S2 | Hồ sơ `browser-final` trong workspace |
| S2 cuối sau sửa navigation và thêm dark320 | 10/10 PASS: desktop/mobile | `browser-results.json`, screenshots |
| TypeScript / toàn bộ ESLint | PASS | `typescript.txt`, `lint.txt` |
| Next16.3.3 production build `--webpack` | PASS; compile32,6s; generate39/39 | `frontend-build.txt` |
| Django system check / makemigrations dry run / migrate check | PASS, không có thay đổi model chưa migration | Kết quả kiểm tra local trong phiên triển khai |
| Local migration | Đạt target infrastructure0004, kéo theo files0017 và S1; backup trước | `local-migrations.txt`, `local-migration-evidence.json` |

Backend test dùng PostgreSQL mới chỉ bind loopback, DB tên riêng, media tạm, email locmem và chặn HTTP storage không mock. Password hash nhanh chỉ dùng trong fixture test. Cluster test đã dừng và thư mục tạm được xóa; không dùng DB ứng dụng để chạy test. Migration reverse/forward trong suite bảo toàn location legacy/provider version, không chứng nhận rollback an toàn cho dữ liệu pin mới.

Chrome dùng giao diện thật với API/S3 fixtures bị intercept, không dùng saved login hoặc tạo bucket thật. Đã xem ảnh desktop, mobile và dark320; sửa crash dữ liệu probe rỗng, tên truy cập của identifier và hai mục navigation cùng active. Kiểm tra mobile ban đầu có assertion chọn navigation đang ẩn; đã sửa assertion để kiểm tra đúng DOM và chạy lại toàn bộ10 bài đạt. Chưa kiểm tra thiết bị vật lý hoặc screen reader.

Build chạy snapshot riêng để giữ `.next` dev. Lần sandbox đầu không tải được Google Fonts; một lần xin thực thi bị giới hạn duyệt tự động. Sau khi hệ thống duyệt hoạt động lại, build tải font và đạt. Warning chọn workspace root do lockfile trong snapshot vẫn còn; không sửa cấu hình ứng dụng chỉ để xóa warning kiểm thử. Không đưa `.env`, session/auth, presigned URL thật hoặc DB backup vào bộ báo cáo.

## Schema local và vận hành

Đã xác minh PostgreSQL đích là127.0.0.1:5432. Backup archive224.201 bytes được kiểm tra bằng pg_restore --list trước migration. Backup riêng giữ trong workspace gitignored, **không xuất Downloads**. Việc kiểm tra archive không đồng nghĩa đã diễn tập restore.

Đã áp dụng infrastructure0001,0002,0003 → files0017 → infrastructure0004 trước khi publish model mới. Cờ control center, multi-cluster routing, LAB probes, agent operations và destructive operations vẫn OFF; registry mặc định rỗng. Không chạy worker cleanup, đổi IAM, bật versioning hoặc tạo/xóa bucket thật trong lượt S2 này. Không dừng/restart tiến trình của người dùng.

Trước khi bật routing phải restart đồng bộ web/finalizer tới cùng version và hoàn tất LAB runbook. Chuẩn bị binding qua UI không tự bật routing. Khi đã có dữ liệu ghim, rollback bằng cờ và giữ reader revision-aware; không tự downgrade schema/code cũ làm mất target. Chi tiết ở ADR-0003/runbook.

## Phần còn lại và gate tiếp theo

G2 cần cluster LAB thật, edition/license được duyệt, identity scoped, TLS/CA, public CORS, version/SSE và thử browser upload/download/worker/cleanup thật, gồm đổi revision giữa upload. HEAD/LAB fixture không chứng minh IAM production, HA/quorum hoặc live health. Certificate fingerprint inventory và provider administrative telemetry chưa được bổ sung; UI giữ health không được giám sát.

S2 chưa giải quyết tính atomic DB/S3 của permanent delete A03; thay đổi tại helper đó chỉ chọn đúng kho. Chưa chứng nhận mọi stale in-flight S3/orphan race A04, crash sau provider commit hoặc phục hồi mất credential bằng MinIO fault injection. Không suy các bài S3 mock đạt thành bằng chứng cho những tình huống này.

S3–S8 vẫn theo gate riêng: React Flow canvas, monitoring, agent, provisioning, maintenance và production rollout chưa triển khai trong S2. Không đánh dấu toàn bộ lộ trình hoàn thành.

Áp dụng `ponytail`, `impeccable`, workflow skill `bluedrive-storage-control-center` đi kèm roadmap và cách viết báo cáo của `humanizer`. Mẫu snapshot → acceptance fail → sửa → kiểm tra riêng → regression → schema trước code → export allowlist có thể bổ sung vào skill hiện có để dùng lại.

Tài liệu kỹ thuật đối chiếu: [Boto3 HeadBucket](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/head_bucket.html) cho phạm vi kiểm tra bucket; [urllib3 connection API](https://urllib3.readthedocs.io/en/stable/reference/urllib3.connection.html) đối chiếu kết nối/TLS. Cách ghim socket được kiểm tra với dependency đã cài, không dựa riêng vào tài liệu phiên bản mới nhất.
