# Platform SeaweedFS — qualification bằng identity runtime

> Phần ngày 13/11 dưới đây giữ bằng chứng lịch sử. [ADR-0010](ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md) đã thay lộ trình MinIO/cutover; không thực thi các đề xuất lịch sử. Kết quả P4 development ngày 17/11/2026 nằm trong mục tiếp nối cuối tài liệu, tách biệt với runtime phục vụ.

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

## Tiếp nối P4 — 17/11/2026, development

### Phạm vi và môi trường đã xác minh

Baseline là `86e41920d85d48360e22796238b863e05604b536` của PR #3, không phải `main`. P4 dùng worktree/nhánh riêng `fix/p4-provider-qualification-safety`; giữ nguyên worktree P1/P2, thay đổi `.vscode/settings.json` có sẵn và 20 paths EXCLUDE. Không thay business logic, dependency, migration, credential hiện hữu, binding hoặc rollout phục vụ.

Platform hiện hữu `bluedrive-seaweedfs` được kiểm tra **chỉ đọc**:

- 8 container running/healthy, SeaweedFS 4.53; Master nhận 4 Volume nodes/21 volumes. Compose nguồn có 3 Volume nodes: đây là drift đã biết, không recreate hoặc xóa node thứ tư.
- SeaweedFS image ID `sha256:ccad23e18639c8b98cee17e7100b95830a06077b56d8e5b006d6dcf8ec5e94a0`; Filer PostgreSQL 17.11 dùng image ID `sha256:e5d2edd28b1f8d40a0a6c0c9cdc545b19b56a0d5d88f94bc11a97d970d4700d0`.
- Named volumes giữ dữ liệu; config private mount read-only. Filer chỉ bật PostgreSQL, DB `seaweedfs_meta`, role `seaweedfs_filer`, 50 rows `filemeta`, một kết nối Filer; role không superuser/CREATEDB/CREATEROLE. Application PostgreSQL 18.6 có DB/role riêng, đọc được trong transaction read-only.
- Host chỉ publish Master/S3 tại loopback `:9333`/`:8333`; Filer/Volume/PostgreSQL metadata nằm trong network riêng. Filer và cả 4 Volume HTTP health trả 200. Django HTTP `:8000` chưa chạy tại thời điểm kiểm tra.
- Identity ứng dụng giới hạn Read/Write/List/Tagging trong `bluedrive-dev`; signed HEAD/versioning/CORS thành công, versioning Enabled, CORS chỉ hai frontend origins local; HEAD bucket fixture lịch sử bị 403. Alias backend khớp identity Platform, khác cả key và secret của Enterprise (chỉ đối chiếu trong RAM).
- Fixture PostgreSQL lịch sử có identity riêng nhưng versioning Disabled/CORS absent; không sửa nó để lấy PASS. Không có identity hiện hữu cho bucket `bluedrive-test-<scope>` mà runner yêu cầu.

Vì vậy gate ghi dùng **project fixture mới độc lập**, không dùng bucket phục vụ: `bluedrive-p4-fixture`, network riêng, Master/S3 loopback `:19333`/`:18533`, bucket `bluedrive-test-p4-platform`. Cùng hai image IDs trên, 7 services, Filer DB/role riêng, credentials mới chỉ cho fixture, không pull/recreate container hiện hữu. Data của fixture dùng tmpfs (không named volumes), config private read-only với ACL bốn principals tin cậy; Master volume limit 64 MiB, mỗi Volume tối đa 4 volumes. Chỉ operator fixture bootstrap bucket mới/versioning/CORS; các bài test dùng application identity giới hạn đúng bucket. Sau gate và đối chiếu cleanup, chỉ 7 container fixture mới được dừng; không dừng/xóa dịch vụ hoặc volumes hiện hữu. Đây không phải restart/recovery test.

Giống kiểm một kho mẫu: quy trình nhận/giao hàng đã chạy trên kho mẫu này; kết quả không tự chứng nhận kho đang phục vụ hoặc khả năng phục hồi dữ liệu lâu dài.

### Gate và kết quả mới

| Gate | Kết quả | Bằng chứng và giới hạn |
| --- | --- | --- |
| Infrastructure/metadata isolation Platform hiện hữu | PASS chỉ đọc | Inventory, Docker mounts/network/images, Master topology, Filer HTTP và PostgreSQL role/database; không thay runtime |
| S3 provider fixture | **8 PASS, 0 SKIP** | PUT/GET/HEAD/DELETE, range, metadata, SHA-256 toàn file, multipart resume/complete lặp/abort, per-part/composite checksums, conditional copy 412, version pinning/delete versions, presigned đúng/sai/hết hạn, CORS và anonymous/bad-key/cross-bucket deny |
| Upload/finalizer fixture | **4 PASS, 0 SKIP** | Hai bài cũ giữ nguyên, thêm hai bài pin/retry; file rỗng/hash sai, worker thật, PostgreSQL test riêng và S3 thật |
| Chrome qualification | PASS trong hai bài pin/retry | Chrome 157.0.8103.79, PUT multipart part + GET version-pinned, origin/host đã ký, SHA-256/ETag receipts được backend đối chiếu; không phải giao diện browser đầy đủ |
| Session/CSRF và direct download ứng dụng | PASS trong bài pin | Login fixture thật, CSRF âm/dương, token CSRF sau login, logout 204/session hết hiệu lực; API cấp URL đúng version và HTTP GET đúng bytes; thu hồi membership chặn cấp URL mới |
| Tenant/Workspace/revision/quota/audit | PASS trong hai bài mới | Default Workspace đúng Tenant, UploadSession/StorageLocation pin connection revision, FileVersion SHA-256, replay cùng idempotency key không tạo thêm upload/file, quota/reservation/audit ghi đúng một lần |
| Publish thành công rồi metadata rollback/retry | PASS | Fault `File.objects.create` sau COPY thật; chưa AVAILABLE, chưa có File, quota vẫn reserved/job pending; retry cùng final key thành công, một logical FileVersion/audit/quota. Không inject lỗi PostgreSQL COMMIT; có thể có nhiều physical S3 versions |
| Provider safety/loopback offline | **4 PASS, 0 SKIP** | Hai negative tests mới cấm admin calls và vẫn reject cross-bucket success, hai HTTP transport tests giữ nguyên |
| Repository/environment/target guards | **30 PASS, 0 SKIP** | Harness hiện có; PostgreSQL test `127.0.0.1:55432`, role/control DB/marker kiểm trước create/drop UUID test DB |
| Security scan working tree | PASS | 659 text files, 5 binary files không được scanner này đọc; không có finding/blocked |
| Security scan index | PASS | Độc lập với working-tree scan; cùng 659 text/5 binary files, không có finding/blocked |
| Remote CI trên source commit | **3 jobs PASS** | Repository-safety/backend/frontend; full Django **662 PASS + 21 SKIP**, enabled fixtures **72 PASS**, guards **30 PASS**, runner no-DB **2 PASS**; pip check/system check/migration consistency PASS; frontend lint/TypeScript/**163 PASS**/build **41/41** |
| Cleanup fixture | PASS | Receipt private ghi trước RPC, đối chiếu 106 exact keys qua các lượt; **0 versions/delete markers, 0 multipart uploads, 0 tài nguyên không có receipt**; không cần xóa bù |
| Persistence Platform hiện hữu | PASS quan sát, không phải recovery gate | Hai fixture object lịch sử khớp size/SHA-256; LastModified trước lần start hiện tại của Filer, 4 Volume và metadata PostgreSQL. Không ghi/xóa probe lịch sử, không restart phục vụ |
| Storage timeout/cleanup failure thật, restore | NOT RUN | Không crash serving services; metadata fault ở trên chỉ đóng một phần failure matrix; tmpfs fixture không chứng minh durability/backup/restore |
| Lifecycle/full application browser | NOT RUN trong P4 live | Rename/move/share/trash/restore/permanent-delete/version restore/concurrent Workspace upload chưa được chứng nhận bằng provider trong lượt này; regression CI không thay bằng chứng live |
| Enterprise runtime/provider/browser | **BLOCKED** | Lab 5 container Exited, S3 `:8433` đóng; network/volumes/config DB/role và credentials riêng được đối chiếu chỉ đọc. Không start/recreate Lab hoặc sửa serving bindings để vượt điều kiện Phase D |

Lệnh live dùng runner hiện có, hai module aliases được chuyển thành đúng hai classes đã duyệt:

```text
python -B -X utf8 infra/seaweedfs/regression.py --live-storage --confirm-live-storage p4-platform files.tests.test_seaweedfs_integration files.tests.test_seaweedfs_finalizer_integration
```

Environment chỉ cấp credential/endpoint của fixture qua private child process; không in stdout/stderr thô hoặc URL ký. Runner vẫn giữ isolated settings/media/email, target guard và UUID PostgreSQL test DB; không migrate application/Filer DB phục vụ. Browser child chỉ nhận OS variables, URL challenge qua stdin và home/cache tạm, không nhận DB/S3 credential hoặc profile người dùng thật.

Lượt đầu 10 bài bị một lỗi receipt writer private trên Windows trước RPC; đổi observer sang JSONL có lock/fsync rồi **10/10 PASS**. Hai bài mới ban đầu bị môi trường Node/Chrome thiếu home/AppData; bổ sung thư mục tạm cho child. Kỳ vọng logout mới được sửa theo contract API hiện có (204). Lượt cuối **12/12 PASS, 0 failures, 0 errors, 0 SKIP**. Log IntegrityError/hash mismatch do fault fixture là dự kiến, không phải suite error. Không hạ assertion bảo mật hoặc đổi nghiệp vụ để lấy PASS.

### Source, Git và CI

- `backend/files/tests/test_seaweedfs_integration.py`: bỏ thử `PutBucketVersioning`/`PutBucketCors` bằng application identity; giữ kiểm tra denial data-plane, thêm hai offline guards. Không chạy bucket-administration mutation để chứng minh deny; phạm vi IAM được kiểm kê read-only.
- `backend/files/tests/test_seaweedfs_finalizer_integration.py`: thêm hai live fixtures/pinned/retry checks, `TransactionTestCase` để quan sát commit/rollback thật, Chrome child cô lập. Hai bài cũ vẫn thực thi.
- `infra/seaweedfs/README.md`: cập nhật phạm vi gate và sửa thông tin font đã lỗi thời; P1 dùng Poppins local theo ADR-0011.
- Tài liệu này giữ các kết quả trên tại đúng nơi qualification, không tạo báo cáo/ADR mới.

Source commit `c5f59580237e14b8f2fccfeba86e00337eb3f142`; [Draft PR #4](https://github.com/binos2303/BlueDrive/pull/4) base `fix/p2-security-business-hardening`. [PR Actions](https://github.com/binos2303/BlueDrive/actions/runs/44092076406) có đủ repository-safety/backend/frontend PASS trên đúng source SHA. Log backend ghi 683 total, 662 executed PASS và 21 provider SKIP, không failures/errors; frontend 163 PASS/0 SKIP và build 41/41. Commit tài liệu tiếp nối giữ nguyên source đã kiểm; SHA và Actions của HEAD cuối được ghi trong body/checks cùng Draft PR để tránh tài liệu tự tham chiếu SHA của chính nó. Chỉ gọi remote PASS cho HEAD cuối khi ba job của đúng SHA hoàn tất; không merge/deploy.

Default CI tiếp tục giữ provider opt-in: 8 SeaweedFS + 4 finalizer + 9 MinIO lịch sử = **21 SKIP**, tăng hai bài live mới so với 19 SKIP của baseline; không giảm số bài thực thi. Hai offline guards mới tăng executed regression từ 660 lên 662. Không chạy lại full local/frontend checks chỉ vì sửa tài liệu/test opt-in; workflow chạy regression backend/frontend thực tế trên commit mới.

### Kết luận và điều kiện trước P5

**P4 PARTIAL**: provider/browser/basic+pinned finalization trên fixture development đã được xác minh; không tuyên bố toàn bộ Platform phục vụ hoặc Enterprise QUALIFIED, không đánh dấu RELEASE ACCEPTED. URL đã phát hành còn residual access đến TTL dù membership bị thu hồi; bài test đã chứng minh giới hạn này thay vì tuyên bố thu hồi tức thời.

Trước P5 cần có CI PASS đúng HEAD cuối, bố trí Enterprise fixture/runtime đủ điều kiện rồi chạy binding/isolation/provider/browser, hoàn tất các live lifecycle/failure gates còn thiếu và diễn tập backup/restore trong phạm vi riêng. Cần operator duyệt riêng nếu các bước đó đụng dữ liệu, migration, routing hoặc restart phục vụ. Snapshot monitoring hiện hữu quá hạn; health/capacity lâu dài và worker liveness còn Unknown, không dùng trạng thái bản ghi cũ thay telemetry mới.

Không có dữ liệu phục vụ cần rollback vì không thay chúng. Rollback source là revert các commit P4 sau review; không tự thực hiện. Receipt/config fixture giữ private; cleanup chỉ theo exact receipt, không `down -v`, không xóa named volumes hoặc kích hoạt lại credential lịch sử. Không bắt đầu P5.
