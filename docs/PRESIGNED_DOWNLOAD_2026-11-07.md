# Download Presigned GET — nghiệm thu local cập nhật 08/11/2026

**Completed cho phạm vi local được cho phép.** Hai điều kiện chặn trước đây (runtime IAM có quyền admin, download chưa ghim phiên bản) đã được xử lý và kiểm chứng. Production chưa được nghiệm thu.

## A. Kiến trúc trước và sau

Trước: browser → Django kiểm tra quyền → đọc toàn bộ object → giải mã/SHA-256 → FileResponse → Blob → lưu file.

Sau, với file mới đủ điều kiện: browser → Django kiểm tra quyền/metadata và HEAD đúng VersionId → cấp URL có versionId → native browser GET MinIO. Django không truyền nội dung; frontend không fetch/giữ Blob cho nhánh này. Giống phiếu giao hàng ghi rõ số hiệu bản lưu: ghi đè cùng tên không thay bản được giao.

File mã hóa ứng dụng, file local cũ và location chưa có VersionId tin cậy vẫn dùng Django. ZIP/preview giữ luồng backend; khi có pin, hàm đọc dùng đúng phiên bản đó.

## B. Files Changed

| File | Thay đổi | Lý do |
|---|---|---|
| `backend/files/views.py`, `urls.py` | Download-url, helper quyền hiện có, eligibility, cookie scope, HEAD/presign đúng version, log authorization | Không cấp URL nhầm quyền/phiên bản |
| `backend/files/storage_adapters/base.py` | ObjectStat.version_id và tham số version_id cho stat/verify/open/presign | Hợp đồng version-aware dùng chung |
| `backend/files/storage_adapters/s3_compatible.py` | Thu VersionId từ SDK, xác minh đúng phiên bản ghi, versioned GET, public signer, Unicode attachment, purge phiên bản | Giữ integrity qua overwrite và cleanup thực sự |
| `backend/files/storage_adapters/factory.py` | Public signer chỉ cấu hình khi flag bật | Rollback nhánh download |
| `backend/files/models.py`, `migrations/0016_storagelocation_provider_version_id.py` | StorageLocation.provider_version_id mặc định trống | Ghim phiên bản, giữ dữ liệu cũ |
| `backend/files/finalization.py` | Lưu VersionId từ kết quả ghi/copy đã xác minh | Gắn DB với đúng object version |
| `backend/securedrive/settings.py`, `backend/.env.example` | Flag mặc định false, public endpoint, TTL/validation | Rollout theo môi trường |
| `backend/minio-dev-policy.json` | Bổ sung GetObjectVersion/DeleteObjectVersion/ListBucketVersions | Read/purge khi bật versioning; không quyền admin |
| `backend/files/tests/test_presigned_download.py`, `test_download_security.py` | Quyền, trạng thái, pin/fallback, crypto thật, fixture dùng chung | Kiểm tra boundary và tương thích |
| `backend/files/tests/test_storage_adapter.py`, `test_finalization_streaming.py`, `test_activity_log_transfers.py`, `test_workspace_upload_quota.py` | Pin, SDK, purge, lưu version và các fixture ObjectStat | Kiểm tra lifecycle |
| `frontend/lib/drive-service.ts` | Native navigation; giữ legacy progress/Blob | Không buffer plaintext direct trong JS |
| `frontend/components/drive/DriveFileBrowser.tsx` | Authorizing/requested, nhiều file, không completed/progress giả | Phản ánh đúng trạng thái |
| `frontend/e2e/download.spec.ts`, `presigned-download-live.spec.ts` | Desktop/mobile và real overwrite/purge/SHA | Nghiệm thu caller và storage thật |
| `frontend/package.json`, `frontend/e2e/README.md`, `docs/MINIO_STORAGE_ADAPTER.md` và báo cáo này | Lệnh test và vận hành/rollback | Có thể kiểm tra lại |

Không đổi upload-service, UploadSession, multipart contract, quota model hay thuật toán mã hóa. Finalizer chỉ được mở rộng để ghi nhận VersionId; các thay đổi khác có sẵn trong worktree được giữ nguyên.

Khi khởi động, Next dev tự sinh frontend/AGENTS.md và frontend/CLAUDE.md theo cơ chế của phiên bản framework đang dùng. Không tạo commit hoặc stage các thay đổi trong lượt này.

## C. Backend Changes

`GET /drive/files/{id}/download-url/` trả `{mode:"presigned",url,filename,size_bytes,expires_in}` hoặc `{mode:"backend"}`. Dùng lại `_get_accessible_file()` / `can_view_file()`, `_download_block_reason()` và `_current_primary_storage_location()`. Selector Workspace tường minh phải hợp lệ, thống nhất và khớp file. Giữ semantics Viewer/Editor và Share hiện hành.

Direct yêu cầu current AVAILABLE version chưa xóa, tenant đúng, PRIMARY location AVAILABLE đúng tenant với storage active; verified_at, checksum/SHA và size thống nhất; provider_version_id không trống/không phải null. Flag tắt, file cần giải mã, dữ liệu cũ chưa pin hoặc endpoint không đủ điều kiện thì giữ backend. Không tự backfill VersionId cũ bằng HEAD mới nhất.

PutObject/CopyObject thu VersionId từ response ghi, rồi HEAD phiên bản đó để xác minh. Finalizer lưu ID này. GET/HEAD/presign mang VersionId; adapter từ chối response sai phiên bản. NoSuchVersion được ánh xạ thành not-found. API không nhận object key, filename hoặc TTL do client chọn. Trạng thái quyền/file/storage giữ 403/404/409; integrity mismatch 422; lỗi kho 503.

`delete_object` liệt kê phiên bản và delete marker, lọc đúng key (không xóa key cùng prefix), kiểm tra pagination và xóa theo batch tối đa 1000. Partial failure báo lỗi để giữ metadata/quota cho retry. Key đã vắng không tạo delete marker mới. Cơ chế này áp dụng cả staging cleanup và permanent delete, độc lập với flag direct.

ActivityLog.DOWNLOAD tiếp tục phục vụ Activity/Admin Audit nhưng direct ghi “Authorized download…”, event=authorization_issued, transport=presigned, version và TTL. Không ghi completed/DECRYPT khi chỉ cấp URL. Không có hệ thống log mới.

### Cấu hình local đã áp dụng

```dotenv
SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED=true
SECUREDRIVE_STORAGE_ENDPOINT_URL=http://127.0.0.1:9000
SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL=http://storage.localhost:9000
SECUREDRIVE_DOWNLOAD_URL_SECONDS=180
SECUREDRIVE_STORAGE_ADDRESSING_STYLE=path
```

Địa chỉ trên minh họa local; bí mật không được đưa vào tài liệu. Backend dùng bucket hiện có `securedrive-files` và danh tính ứng dụng mới giới hạn bucket. Mẫu policy trong source dùng ARN securedrive-dev cho ví dụ; policy local đã được đặt đúng bucket đang cấu hình.

Ngày 07/11 người dùng cho phép rõ việc mở rộng local: migration, IAM giới hạn, versioning và cập nhật cấu hình sau kiểm thử. Migration 0016 đã áp dụng; đối chiếu các hàng file và metadata storage cũ không đổi. Bucket được bật versioning, không xóa dữ liệu cũ, không thu hồi danh tính cũ. Credentials runtime đã đổi qua file .env cục bộ; bản sao cấu hình cũ được giữ trong `backend/.env.download-local-backup`, gitignored và ACL giới hạn người dùng hiện tại/SYSTEM. Không gửi credentials qua chat hoặc log.

Public signer dùng client chung nếu endpoint giống; khác endpoint thì chỉ tạo signer khi cần. Không rewrite URL sau khi ký. Native download chỉ được cấp khi hostname/phạm vi cookie tách khỏi ứng dụng; khác port không tạo cách ly cookie. Production vẫn yêu cầu HTTPS/TLS verification/SSE theo settings và cần nghiệm thu riêng.

### Rollback

Đặt flag false và restart backend để dùng legacy; giữ schema VersionId, IAM version permissions và cleanup version-aware. Tắt feature không tắt versioning. Không rollback bằng cách xóa version, hạ schema hoặc khôi phục quyền admin cho runtime. Danh tính cũ được giữ cho vận hành, không còn dùng trong request ứng dụng.

## D. Frontend Changes

Direct tạo anchor không đưa vào DOM, noopener/noreferrer, target blank; không dùng thuộc tính download để quyết định tên cross-origin. Tên file do Content-Disposition attachment UTF-8 của kho quyết định. Browser tự quản lý progress/lỗi/lưu file.

UI báo Preparing/Authorizing rồi Requested… và hướng dẫn xem browser downloads. Không vẽ phần trăm hoặc báo Completed cho native. Legacy/ZIP giữ progress thật và chỉ xác nhận received sau khi nhận đủ bytes. Retry xin URL mới; không tự fallback khi native lỗi hoặc URL hết hạn. Không lưu signed URL trong local/sessionStorage, analytics hay log; không gắn cookie ứng dụng/Authorization/Workspace/Referer vào GET kho.

Source có menu ba chấm dùng ContextMenu, chưa có row right-click handler. Đã kiểm tra menu hiện hữu, toolbar, nhiều file, Workspace context và các viewport; không thêm tính năng ngoài scope.

## E. Tests và bằng chứng

| Kiểm tra | Kết quả |
|---|---|
| Backend files, ZIP, activity/self-service/pagination, CORS Workspace | 152 cases: 143 PASS, 9 SKIP tùy chọn |
| Adapter sau bổ sung NoSuchVersion | 31/31 PASS, có trùng các ca của bộ trên |
| Native/legacy/ZIP/lỗi/quyền/multiple/menu/toolbar/retry trên desktop/mobile Chrome | 20/20 PASS |
| TypeScript và toàn bộ ESLint frontend | PASS |
| Unit download policy | 3/3 PASS |
| Next.js production build | PASS; lượt đầu sandbox không tải được Google Font, chạy lại với network được phép đã đạt |
| Django check, makemigrations --check --dry-run, diff check | PASS |
| Live 16 MiB, native URL/version pin/overwrite/SHA/purge | PASS qua backend chính sau bật rollout |
| Live Workspace upload/quota 9 MiB | PASS với danh tính ứng dụng và bucket versioned |

152 backend cases chạy với PostgreSQL test DB tên riêng, media/email cách ly. Chín ca tùy chọn thuộc module integration dành cho bucket thử riêng/fault proxy chưa bật; không tính là PASS.

Live native: upload UI → finalizer → AVAILABLE → API thật cấp URL có versionId. Test giữ response cấp quyền, ghi đè duy nhất fixture cùng key và cùng kích thước bằng dữ liệu khác, rồi chuyển URL gốc cho browser. File tải về vẫn đúng bytes/SHA-256 của phiên bản ban đầu; native download.url bằng URL kho, không Blob hoặc binary proxy Django; tên tiếng Việt đúng. Cleanup xác nhận cả hai phiên bản primary và staging đã biến mất, quota về 0, Workspace thử archive. GET anonymous bỏ chữ ký bị 403.

Lượt trước gián đoạn dùng API thật tạm ở cổng 8001 với TTL 5 giây và cùng danh tính hạn chế; đã PASS kiểm tra URL hết hạn bị 403. Lượt nghiệm thu cuối 08/11 đi qua backend chính 8000 với TTL local mặc định 180, không dùng API tạm. Không triển khai mock response của kho.

Workspace live: hai admission đồng thời một được reserve/một bị từ chối quota, abort giải phóng reserve, upload hai part, backend download so khớp bytes, quota cá nhân không đổi; chỉ fixture riêng được xóa, Workspace riêng được archive. Không đổi quota policy/membership người dùng.

Runtime IAM được đọc lại sau khi Docker/kho cũ khởi động lại: đúng 9 Allow actions S3 giới hạn bucket, không admin:* / s3:* / kms:*. Runtime bị từ chối get_bucket_versioning và thao tác quản trị user; kiểm tra vận hành bằng danh tính cũ xác nhận versioning Enabled.

Artifact gitignored:
- `frontend/playwright-report/download-final-mocked/index.html`
- `frontend/playwright-report/download-rollout-live/index.html`
- `frontend/playwright-report/workspace-versioned/index.html`
- Lượt TTL ngắn/pin trước đó: `frontend/playwright-report/download-pinned-live/index.html`

Trace/video tắt; ảnh và session riêng có thể chứa tên tài khoản/file. Chưa thử thiết bị vật lý, proxy/TLS production, tải đồng thời lớn hoặc file mã hóa riêng của người dùng. Crypto thật/các quyền bị thu hồi và SCANNING được kiểm tra trong test DB, không sửa quyền hoặc nội dung người dùng thật để thử.

## F. Security Review

- Django kiểm tra quyền tại thời điểm cấp URL; key và VersionId lấy từ metadata tin cậy, không từ request tùy ý.
- Bucket private: anonymous GET fixture hiện hữu bị từ chối. Không đổi bucket public.
- Pin lấy từ kết quả ghi đã xác minh; GET ghim version chống đổi bytes khi cùng key bị overwrite. Không dùng ETag multipart thay SHA-256.
- IAM runtime đã bỏ quyền quản trị/wildcard actions; quyền giới hạn đúng bucket, có các quyền version cần cho đọc và purge. Bí mật mới/cũ không commit hoặc hiển thị.
- SDK không trả Secret Key/DEK/KEK; SigV4 URL tự chứa credential identifier/scope theo chuẩn, cả URL là bearer capability nhạy cảm.
- TTL cấu hình mặc định 180, no-store; URL đã cấp có thể dùng lại tới hết hạn. Thu hồi membership/share chặn cấp mới, không hứa thu hồi tức thời URL cũ.
- Download/deletion version-aware được kiểm tra thật sau ghi đè. Flag rollback giữ cleanup an toàn khi bucket tiếp tục versioned.
- Danh tính runtime/vận hành vẫn có thể xóa phiên bản theo quyền được cấp; đây là khả năng quản trị availability, không phải bảo đảm WORM/Object Lock chống mọi quản trị viên.

## G. Remaining Risks

| Phạm vi | Giới hạn/hướng xử lý |
|---|---|
| Production | Chưa áp dụng hoặc nghiệm thu IAM, TLS, reverse proxy, DNS và tải của production; không đưa cấu hình localhost lên production |
| Dữ liệu cũ | Chưa có pin tin cậy thì legacy; muốn chuyển cần quy trình đọc/xác minh/công bố riêng, không suy đoán ID |
| Bearer URL | Có thể replay đến TTL; giữ TTL ngắn và tránh logs/tracing chứa query |
| Native browser | Progress/lỗi GET thuộc browser, nhiều tải có thể cần cấp phép; UI chỉ xác nhận đã gửi request |
| Storage operator | Không có Object Lock/WORM; xóa version có quyền vẫn làm mất khả năng tải. Policy/lưu giữ backup là quyết định vận hành riêng |

Hai mục High của bản nghiệm thu trước đã đóng cho local: runtime không còn dùng danh tính admin; URL và backend reads đã ghim VersionId, có bằng chứng overwrite isolation và purge.

## H. Final Status

**Completed — phạm vi refactor và rollout local được cho phép.** Flag local đã bật; backend/frontend/finalizer được khởi động bằng cấu hình ứng dụng mới. Không còn bước phê duyệt local đang chờ. Danh tính cũ và dữ liệu hiện có được giữ; chỉ fixture do test tạo được xóa.

Có thể đóng gói quy trình fixture riêng → kiểm tra IAM chỉ đọc → upload/pin → overwrite isolation → native GET/SHA → cleanup/quota thành Agent Skill dùng lại.

Đối chiếu: [Boto3 presigned URLs](https://docs.aws.amazon.com/boto3/latest/guide/s3-presigned-urls.html), [S3 GetObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html), [xóa object versions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/DeletingObjectVersions.html), [cookie scope](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Cookies).
