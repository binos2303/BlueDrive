# Platform SeaweedFS — qualification bằng identity runtime

Ngày **13/11/2026**, Asia/Bangkok. Tiếp nối [checkpoint trước qualification](PLATFORM_CUTOVER_CHECKPOINT_2026-11-13.md), [ADR-0008](ADR-0008-platform-storage-copy-and-publication.md) và [runbook Platform](../infra/seaweedfs/README.md).

**Báo cáo đang chờ kết quả triển khai/kiểm thử và quyết định schema phục vụ.** Chưa có bằng chứng mới để đổi revision thật thành READY. Copy, publication, binding/routing, dừng MinIO và xử lý dữ liệu nguồn chưa được phê duyệt trong nhiệm vụ qualification này.

## Nguyên nhân và phạm vi sửa

Probe LAB trước đây dùng cùng identity ứng dụng để tạo, tag, bật versioning/CORS và xóa bucket tạm. Identity Platform hiện có chỉ có bốn nhóm action `Read`, `Write`, `List`, `Tagging` trên bucket `bluedrive-dev`. Read check thành công nhưng provisioning bucket mới bị từ chối, khiến revision thất bại và probe `cleanup_pending` dù `bucket_created=false`.

Đây là hai trách nhiệm khác nhau: operator chuẩn bị kho; nhân viên nhận/giao hàng kiểm tra trong kho được giao. Qualification runtime phải kiểm chứng thẻ nhân viên hiện có, không cần trao thêm quyền mở hoặc sửa kho.

| Hạng mục | Provisioning | Qualification runtime |
| --- | --- | --- |
| Bucket | Operator tạo/cấu hình theo phạm vi đã duyệt | Bucket trong connection revision đã được duyệt |
| Identity | Operator riêng | Cùng identity ứng dụng của revision |
| Bucket administration | Có thể cần khi được duyệt | Không yêu cầu CreateBucket/PutBucketPolicy hoặc thay CORS/versioning |
| Fixture | Bucket LAB mới riêng theo quy trình cũ | Key/version/upload fixture có ownership và receipt riêng |
| Cleanup | Đúng bucket LAB của probe | Chỉ exact fixture versions/uploads trong bucket hiện hữu |
| Kết quả | Provisioning hoàn tất không tự làm READY | READY đòi toàn bộ required checks, browser proof và cleanup đạt |

IAM trước/sau được kiểm tra độc lập: giữ nguyên bốn action giới hạn bucket; không thêm Admin, wildcard bucket, credential hoặc identity mới. Bằng chứng đọc mới đã xác nhận HEAD bucket, versioning Enabled và CORS bằng identity ứng dụng; cross-bucket HEAD bị 403. `GetBucketPolicy` trả `NoSuchBucketPolicy` là cấu hình vắng mặt, không phải bằng chứng một quyền quản trị bị từ chối. Các thao tác runtime bắt buộc bị deny phải làm qualification FAIL; thao tác provisioning không cần thiết không được dùng làm gate thất bại.

## Hợp đồng bảo vệ cần xác minh

- Scope và target lấy từ profile/revision phía server; không nhận endpoint, bucket, credential hoặc key tùy ý từ browser.
- API/service kiểm actor active, quyền cấu hình đúng Platform/Organization, session/CSRF và origin được duyệt. Platform admin không thay quyền Organization.
- Probe runtime giữ bucket revision và key/receipt có định danh riêng. Không gọi API quản trị bucket khi bắt đầu, thất bại, retry hoặc cleanup.
- Chứng minh PUT/GET/HEAD/DELETE, immutable version, multipart, presigned PUT/GET, SHA-256 toàn bytes, metadata, CORS/browser và cross-bucket denial bằng cùng identity runtime.
- Không dùng ETag/composite checksum thay SHA-256 toàn file. Không đổi host sau ký; URL tạm không được ghi log/manifest công khai.
- READY chỉ khi toàn bộ check bắt buộc và cleanup thành công, generation/expiry còn hợp lệ. Thiếu quyền cần thiết, browser proof hoặc receipt cleanup không được quy thành PASS.
- Lỗi cleanup giữ trạng thái pending, retry an toàn và lịch sử/audit. Reconcile probe LAB cũ cần proof bucket vắng mặt thật; 403 hoặc `bucket_created=false` riêng lẻ chưa chứng minh vắng mặt.

## Schema và trạng thái thật

Migration probe mới phụ thuộc `infrastructure.0006_allow_deleted_upload_history`. Vì vậy áp dụng vào DB phục vụ sẽ gồm cả thay trigger lifecycle đã chuẩn bị trước, không chỉ thêm trường qualification. Phải trình SQL/digest, backup và diễn tập restore/migration cụ thể trước quyết định schema phục vụ. Không cập nhật SQL trực tiếp để gán READY, bỏ cleanup pending hoặc đổi revision identity.

Trạng thái baseline theo checkpoint trước: cluster `f3ae021f-e3bb-4ba2-a0e7-d1991a6de0cf`, revision 1 `3bd9b5d0-8dfb-4b15-8b4f-41d77b54958a` thất bại; probe LAB `418a7548-b03d-43b8-b49f-5763a63c5d4f` cleanup pending và fixture không tồn tại đã được operator kiểm tra. Đây là số liệu checkpoint, chưa phải kết quả qualification mới.

## Kiểm chứng của nhiệm vụ này

| Nhóm | Trạng thái hiện tại | Bằng chứng cần chốt |
| --- | --- | --- |
| Least-privilege identity / read-only IAM | PASS phần kiểm kê | Cùng identity và scope bucket hiện hữu; không đổi config |
| Backend qualification/security tests | PENDING | Lệnh, số bài thực thi, fail/skip, negative/cleanup/retry cases |
| SeaweedFS/browser/multipart runtime | PENDING | Required calls và browser thật, receipts/cleanup |
| Probe LAB cũ / retry revision | PENDING | Service/audit, absence proof, lịch sử được giữ |
| Serving schema / revision READY | PENDING | Quyết định schema, migration thực tế, probe persisted và verified_at |
| Migration plan / readiness regression | PENDING | Plan-only sau qualification; không copy/publication |
| Frontend | SKIP | Không thay UI/client; không tái dùng số test cũ thành lần chạy mới |

## Readiness sau qualification

Qualification READY sẽ đóng gate năng lực data-plane của revision tại môi trường local này. Nó không tự phê duyệt cutover hoặc chứng nhận production TLS/SSE/HA. Trước action ghi dữ liệu thật vẫn phải đối chiếu:

1. Upload, job, reservation và multipart đang hoạt động; xác nhận nguồn không đổi tại cửa sổ dừng writer và chờ hết hạn URL PUT đã cấp.
2. Backup DB/object/key/config khớp inventory đã đóng băng, restore cách ly và rollback còn khả dụng. Backup local không chứng minh độ bền off-host.
3. Schema phục vụ đúng phiên bản đã duyệt; web/worker nạp cùng code, profile và alias credential.
4. Manifest target/source hiện hành, exact IDs và digest; plan-only không cấp quyền copy/publication/routing.
5. 48 session legacy cần phân loại theo tham chiếu thực tế; không xóa history/quota/audit hoặc source keys để làm sạch báo cáo. Location nguồn vẫn cần cho rollback/permanent-delete.
6. Phê duyệt riêng cho copy/publication và routing, rồi nghiệm thu ứng dụng thật My Drive/Personal Workspace/Finalizer/quota/sharing/trash/restore. MinIO/Enterprise/volumes được giữ.

Kết luận sẽ tách **CODE COMPLETE**, **QUALIFICATION VERIFIED** và **CUTOVER APPROVED** theo bằng chứng mới; hiện hai mục đầu chưa chốt và cutover chưa được phê duyệt.
