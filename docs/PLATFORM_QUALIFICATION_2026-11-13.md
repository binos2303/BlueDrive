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
| Upload/finalizer fixture | **5 PASS, 0 SKIP** | Hai bài cũ giữ nguyên, thêm pin/retry/concurrent Workspace; file rỗng/hash sai, worker thật, PostgreSQL test riêng và S3 thật |
| Chrome qualification | PASS trong ba bài pin/retry/Workspace | Chrome 157.0.8103.79, PUT multipart part + GET version-pinned, origin/host đã ký, SHA-256/ETag receipts được backend đối chiếu; không phải giao diện browser đầy đủ |
| Session/CSRF và direct download ứng dụng | PASS trong bài pin | Login fixture thật, CSRF âm/dương, token CSRF sau login, logout 204/session hết hiệu lực; API cấp URL đúng version và HTTP GET đúng bytes; thu hồi membership chặn cấp URL mới |
| Tenant/Workspace/revision/quota/audit | PASS trong hai bài mới | Default Workspace đúng Tenant, UploadSession/StorageLocation pin connection revision, FileVersion SHA-256, replay cùng idempotency key không tạo thêm upload/file, quota/reservation/audit ghi đúng một lần |
| Publish thành công rồi metadata rollback/retry | PASS | Fault `File.objects.create` sau COPY thật; chưa AVAILABLE, chưa có File, quota vẫn reserved/job pending; retry cùng final key thành công, một logical FileVersion/audit/quota. Không inject lỗi PostgreSQL COMMIT; có thể có nhiều physical S3 versions |
| Lifecycle với S3 thật | PASS trong bài pin | JSON APIs rename/move/share/trash/restore giữ nguyên location/key/version/bytes; recipient fixture nhận URL đọc được, file trong trash không được cấp URL. Owner dùng login/CSRF thật, recipient dùng fixture session `force_login` |
| Workspace quota đồng thời | PASS | Hai requests qua DB connections riêng/barrier và S3 multipart init thật, một 201/một 413; upload thắng được PUT/complete/finalize, Workspace consumed 60/reserved 0, hai tenant personal quotas không bị tính, một File/audit/reservation consumed. Editor được `force_authenticate` để tách kiểm quota khỏi login |
| Timeout và cleanup fault | PASS với fault injection | Adapter `download_to` lỗi retryable sau metadata rollback: quota vẫn reserved/job pending, lần thứ ba đọc/copy S3 thật thành công. Delete timeout trả 503, giữ File/FileVersion/location ERROR/quota/bytes; retry xóa S3 versions/metadata thật và quota về 0. Không giả lập crash/TCP outage thực tế |
| Provider safety/loopback offline | **4 PASS, 0 SKIP** | Hai negative tests mới cấm admin calls và vẫn reject cross-bucket success, hai HTTP transport tests giữ nguyên |
| Repository/environment/target guards | **30 PASS, 0 SKIP** | Harness hiện có; PostgreSQL test `127.0.0.1:55432`, role/control DB/marker kiểm trước create/drop UUID test DB |
| Security scan working tree | PASS | 659 text files, 5 binary files không được scanner này đọc; không có finding/blocked |
| Security scan index | PASS | Độc lập với working-tree scan; cùng 659 text/5 binary files, không có finding/blocked |
| Remote CI snapshot trước bổ sung lifecycle | **3 jobs PASS trên c5f5958/68f5db0** | Repository-safety/backend/frontend; full Django **662 PASS + 21 SKIP**, enabled fixtures **72 PASS**, guards **30 PASS**, runner no-DB **2 PASS**; pip check/system check/migration consistency PASS; frontend lint/TypeScript/**163 PASS**/build **41/41**. HEAD cuối có thêm một live test; dùng SHA/Actions trong body/checks Draft PR #4 để xác minh kết quả hiện hành |
| Cleanup fixture | PASS | Receipt private ghi trước RPC, đối chiếu 137 exact keys qua các lượt; **0 versions/delete markers, 0 multipart uploads, 0 tài nguyên không có receipt**; không cần xóa bù |
| Persistence Platform hiện hữu | PASS quan sát, không phải recovery gate | Hai fixture object lịch sử khớp size/SHA-256; LastModified trước lần start hiện tại của Filer, 4 Volume và metadata PostgreSQL. Không ghi/xóa probe lịch sử, không restart phục vụ |
| Outage/backup/restore thật | NOT RUN | Không crash serving services; fault injection ở trên không chứng minh recovery sau mất node/DB hoặc backup/restore; tmpfs fixture không chứng minh durability |
| Full application browser | NOT RUN | Chrome challenge thật và API/middleware integration được tách khỏi toàn bộ giao diện upload/lifecycle; không tái dùng mocked browser baseline thành live proof |
| Version restore | NOT IMPLEMENTED | Không tìm thấy API/implementation hiện hành; không mở rộng nghiệp vụ để ép kiểm thử |
| Enterprise runtime/provider/browser | **BLOCKED** | Lab 5 container Exited, S3 `:8433` đóng; network/volumes/config DB/role và credentials riêng được đối chiếu chỉ đọc. Không start/recreate Lab hoặc sửa serving bindings để vượt điều kiện Phase D |

Lệnh live dùng runner hiện có, hai module aliases được chuyển thành đúng hai classes đã duyệt:

```text
python -B -X utf8 infra/seaweedfs/regression.py --live-storage --confirm-live-storage p4-platform files.tests.test_seaweedfs_integration files.tests.test_seaweedfs_finalizer_integration
```

Environment chỉ cấp credential/endpoint của fixture qua private child process; không in stdout/stderr thô hoặc URL ký. Runner vẫn giữ isolated settings/media/email, target guard và UUID PostgreSQL test DB; không migrate application/Filer DB phục vụ. Browser child chỉ nhận OS variables, URL challenge qua stdin và home/cache tạm, không nhận DB/S3 credential hoặc profile người dùng thật.

Lượt đầu 10 bài bị một lỗi receipt writer private trên Windows trước RPC; đổi observer sang JSONL có lock/fsync rồi **10/10 PASS**. Hai bài mới ban đầu bị môi trường Node/Chrome thiếu home/AppData; bổ sung thư mục tạm cho child. Kỳ vọng logout mới được sửa theo contract API hiện có (204), rồi **12/12 PASS**. Tiếp tục đóng lifecycle/timeout/cleanup/Workspace gates trên cùng fixture, lượt cuối **13/13 PASS, 0 failures, 0 errors, 0 SKIP**. Log IntegrityError/hash mismatch/retryable error do fault fixture là dự kiến, không phải suite error. Không hạ assertion bảo mật hoặc đổi nghiệp vụ để lấy PASS.

### Source, Git và CI

- `backend/files/tests/test_seaweedfs_integration.py`: bỏ thử `PutBucketVersioning`/`PutBucketCors` bằng application identity; giữ kiểm tra denial data-plane, thêm hai offline guards. Không chạy bucket-administration mutation để chứng minh deny; phạm vi IAM được kiểm kê read-only.
- `backend/files/tests/test_seaweedfs_finalizer_integration.py`: thêm ba live fixtures pin/retry/Workspace, kiểm lifecycle và timeout/cleanup fault, `TransactionTestCase` để quan sát commit/rollback thật, Chrome child cô lập. Hai bài cũ vẫn thực thi.
- `infra/seaweedfs/README.md`: cập nhật phạm vi gate và sửa thông tin font đã lỗi thời; P1 dùng Poppins local theo ADR-0011.
- Tài liệu này giữ các kết quả trên tại đúng nơi qualification, không tạo báo cáo/ADR mới.

Source commit ban đầu `c5f59580237e14b8f2fccfeba86e00337eb3f142`; [Draft PR #4](https://github.com/binos2303/BlueDrive/pull/4) base `fix/p2-security-business-hardening`. [PR Actions source ban đầu](https://github.com/binos2303/BlueDrive/actions/runs/44092076406) và [snapshot tài liệu 68f5db0](https://github.com/binos2303/BlueDrive/actions/runs/44093638191) có đủ ba jobs PASS; backend 683 total, 662 executed PASS/21 provider SKIP, frontend 163 PASS/0 SKIP/build 41/41. Sau đó mở rộng các gate lifecycle/Workspace còn có thể thực hiện an toàn. SHA và Actions của HEAD cuối (có phần bổ sung này) được ghi trong body/checks cùng Draft PR để tránh tài liệu tự tham chiếu SHA của chính nó. Chỉ gọi remote PASS cho HEAD cuối khi ba job của đúng SHA hoàn tất; không merge/deploy.

Default CI tiếp tục giữ provider opt-in: 8 SeaweedFS + 5 finalizer + 9 MinIO lịch sử = **22 SKIP**, tăng ba bài live mới so với 19 SKIP của baseline; không giảm số bài thực thi. Hai offline guards mới tăng executed regression từ 660 lên 662 (684 total dự kiến). Không chạy lại full local/frontend checks chỉ vì sửa tài liệu/test opt-in; workflow chạy regression backend/frontend thực tế trên commit mới.

### Kết luận và điều kiện trước P5

**P4 PARTIAL**: provider/browser/basic+pinned finalization trên fixture development đã được xác minh; không tuyên bố toàn bộ Platform phục vụ hoặc Enterprise QUALIFIED, không đánh dấu RELEASE ACCEPTED. URL đã phát hành còn residual access đến TTL dù membership bị thu hồi; bài test đã chứng minh giới hạn này thay vì tuyên bố thu hồi tức thời.

Trước P5 cần có CI PASS đúng HEAD cuối, bố trí Enterprise fixture/runtime đủ điều kiện rồi chạy binding/isolation/provider/browser, hoàn tất full application browser và diễn tập outage/backup/restore trong phạm vi riêng. Cần operator duyệt riêng nếu các bước đó đụng dữ liệu, migration, routing hoặc restart phục vụ. Snapshot monitoring hiện hữu quá hạn; health/capacity lâu dài và worker liveness còn Unknown, không dùng trạng thái bản ghi cũ thay telemetry mới.

Không có dữ liệu phục vụ cần rollback vì không thay chúng. Rollback source là revert các commit P4 sau review; không tự thực hiện. Receipt/config fixture giữ private; cleanup chỉ theo exact receipt, không `down -v`, không xóa named volumes hoặc kích hoạt lại credential lịch sử. Không bắt đầu P5.

## P4 final qualification — 18/11/2026

### Phạm vi và ranh giới bằng chứng

Tiếp tục từ `b7933a3f8e68b85620493f0a7b17292a105a4258`, cùng nhánh và [Draft PR #4](https://github.com/binos2303/BlueDrive/pull/4). Bằng chứng 17/11 ở trên giữ nguyên theo thời điểm; phần này đóng các gate A/B/C bằng fixture mới. Không đổi business logic, schema, endpoint/key/credential/binding/flag hoặc dữ liệu phục vụ. Không chạy lại 13 provider tests/full local Django khi backend không đổi.

Operator đã duyệt mở Docker Desktop ở nền; Engine 29.8.2 tự khôi phục Platform theo restart policy. Không chủ động restart/recreate Platform hoặc khởi động Enterprise Lab cũ. Tạo riêng bốn project `bluedrive-p4-final-{app,platform,enterprise-a,enterprise-b}`, 16 container/16 named volumes, network riêng, `restart: no`, image cache đã pin, không pull. Application PostgreSQL 18.6 tại loopback `55433`, role/database riêng và marker `BlueDrive P4 final isolated application fixture v1`; role không superuser/CREATEDB/CREATEROLE. Mỗi SeaweedFS 4.53 có Master/Volume/Filer/S3 và PostgreSQL Filer 17.11 riêng; S3 loopback `18633/18643/18653`, public signer `s3.localhost` cùng port, bucket/identity fixture riêng. Images SeaweedFS/Filer PostgreSQL giữ digest đã ghi ở phần 17/11.

Django fixture dùng settings ứng dụng, process environment allowlist, dotenv bị tắt, SECRET/AES/DB/S3 keys mới chỉ dành fixture, MEDIA_ROOT riêng và email locmem. Không lấy tài khoản hoặc private configuration phục vụ. Backend `127.0.0.1:18000` không autoreload, Next production `127.0.0.1:13000`, worker `run_upload_finalizer` hiện có. Session/CSRF/quyền/quota vẫn thực thi. Routing/direct download/runtime probes chỉ bật trong process fixture, lab probe tắt; connection đi qua read check + Chrome challenge + READY + binding API/services, không gán READY trực tiếp. HTTP development/SSE trống không chứng nhận TLS/SSE/CSE production.

Manifest kiểm project labels, image IDs, network, named-volume ownership, private bind read-only và loopback ports trước thao tác container. Receipt JSONL có lock/fsync ghi trước S3 RPC, chặn bucket administration và key/endpoint ngoài fixture. Private config, auth state, screenshots, dumps và cold archives ở `.python/p4-final-fixture`/`.python/p4-final-restored-fixture`, ACL protected bốn trusted principals; Git ignore, không stage/publish.

### Kết quả thực thi mới

| Gate | Kết quả | Bằng chứng và giới hạn |
| --- | --- | --- |
| A — My Drive UI thật | **2 PASS, 0 FAIL, 0 SKIP** | Desktop 1440×900 và mobile touch 390×844: login/session/CSRF thật; tạo folder; browser PUT hai parts tổng 9 MiB tới đúng Platform S3; server AVAILABLE trước UI completed; native attachment dùng nguyên URL được Django cấp, có VersionId/chữ ký, bytes/SHA-256 khớp; rename/move/share viewer/trash/restore qua UI. Không intercept API/storage, không binary proxy cho native download, không gửi cookie/X-Workspace-ID tới S3, không client/network error bất ngờ. Mobile là emulation, chưa phải thiết bị thật. |
| A — Workspace UI/quota | **2 PASS, 0 FAIL, 0 SKIP** | Desktop/mobile: tạo Workspace fixture, hai admission đồng thời trả 201/413, abort trả reservation; upload 9 MiB qua browser; kiểm proxy bytes và native UI download đúng bytes từ `s3.localhost:18633` có version pin. Chỉ quota Workspace tăng, Personal quota không đổi; xóa exact verified file và archive Workspace rỗng. |
| B — Enterprise provisioning/isolation | **PASS, hai Organizations/hai clusters** | Dùng create_organization/create_employee, email locmem invitation và accept_invitation hiện có cho sáu managed accounts. My Drive riêng thuộc Organization. Thiếu binding, routing OFF và connection chưa READY đều deny trước upload/reservation/S3 write, không fallback Platform. Wrong-Tenant binding API 404 và binding không đổi. Hai real uploads/downloads pin đúng revision/bucket/port; SHA/size/version khớp. Org Admin và Org khác không đọc private employee file. Thu hồi membership fixture chặn URL mới; đây là status fixture, không nghiệm thu offboarding workflow đầy đủ. URL đã cấp vẫn có residual access đến TTL. |
| B — Enterprise UI/browser thật | **2 PASS, 0 FAIL, 0 SKIP** | Enterprise A peer desktop và Enterprise B employee mobile chạy đầy đủ lifecycle UI như My Drive, signed PUT/GET đúng ports `18643/18653`, Chrome CORS thật. Employee không có `storage.view` nhận 404 capability theo contract và không thấy link Organization storage; explicit share mới cấp quyền cho đúng recipient. Platform Personal vẫn hoạt động độc lập. |
| C — S3 Gateway outage trong multipart | **PASS** | Dừng chỉ Gateway fixture sau part 1 (8 MiB); part 2 không thể gửi, session UPLOADING/chưa File, quota reserved. Start lại cùng container/volumes; ListParts xác minh part 1 còn nguyên, gửi part 2, complete/finalize đúng một logical version/quota/audit. Không tạo upload mới để né lỗi. |
| C — S3/Filer outage trong finalization | **2 cases PASS** | Dừng worker fixture đã xác minh PID/path/timestamp. Mỗi case complete vào VERIFYING rồi stop đúng Gateway hoặc Filer; chạy finalize_uploads thật: job pending/attempt 1, reservation giữ nguyên, chưa File/AVAILABLE. Start đúng service, retry attempt 2 DONE/AVAILABLE; lặp worker không nhân đôi publication/accounting/audit. Không mock provider hoặc sửa assertion/business logic. |
| C — Persistence | **PASS, 11 pinned files** | Restart chỉ 16 container fixture, gồm application PG và cả ba Filer PG. Tất cả rows của mọi bảng public ứng dụng khớp snapshot trước restart; 11 file còn giữ theo receipts khớp SHA-256/size/provider version/revision/owner/Tenant/Workspace. Tập này gồm file của các lượt harness chưa PASS; không tính các lượt đó thành test PASS. Quota/reservation/audit nguyên trạng. |
| C — Backup/restore khác môi trường | **PASS** | Dừng fixture web/worker trước consistency snapshot; dừng S3/Filer writers trước pg_dump custom-format. Backup app PG, ba Filer PG, cold `/data` của Master/Volume/Filer/S3 và private recovery config. Restore vào bốn project `bluedrive-p4-final-restore-*`, networks và 16 named volumes mới; source giữ dừng/nguyên vẹn. Dùng lại loopback ports sau khi source dừng để bảo toàn pinned endpoint identity, không sửa revisions. Restore app schema/data vào DB rỗng; Filer data vào bootstrap schema rỗng, không drop/reset DB. |
| C — Xác minh sau restore | **PASS** | Mọi rows ứng dụng khớp consistency snapshot; Filer row counts 50/32/32 khớp backup. Đọc thực 11 provider versions, so SHA/size và ownership. Quota used khớp tổng file đúng scope, reserved 0, reservation consumed, một current FileVersion/location/UPLOAD audit cho mỗi logical file còn tồn tại. Django độc lập với cấu hình restored thực hiện 5 signed reads hợp lệ (owner/viewer/employee) đúng bytes, 7 denials cho Org Admin/cross-Org/revoked membership, kể cả header Workspace tường minh. Không chỉ kiểm import thành công. |
| UI regression có mock | **66 PASS, 0 FAIL, 0 SKIP** | 33 desktop + 33 mobile của mocked/organization-provisioning/p2-hardening; riêng với sáu ca real UI ở trên, không dùng mock PASS thay provider. |
| Frontend | **PASS** | Lint, TypeScript, 163 Node tests/0 SKIP, production build Next 16.4.6 41/41. Framework update khiến chạy lại các checks liên quan; không sửa UI để né build failure. |
| Security scans | **PASS độc lập** | Working tree 660 text files; index trước stage 659 text files; mỗi scope 5 binary files scanner không đọc. Index sẽ được quét lại sau stage. Scanner không thay secret scanner đầy đủ hoặc disposition Git history đã duyệt ở P1. |

Các lệnh thực thi dùng Python 3.12.10 `.venv` chung, helper fixture private có target/manifest guards; không tạo venv khác. Entry points ứng dụng/provider giữ nguyên: `manage.py migrate` chỉ trên app fixture mới; `runserver 127.0.0.1:18000 --noreload`, `run_upload_finalizer`, `finalize_uploads`; Playwright chạy `p4-qualification.live.spec.ts` và `workspace-upload.spec.ts` từng project. Backup dùng `docker exec <verified-fixture-id> pg_dump -Fc`, cold `docker cp <verified-fixture-id>:/data/. -`, restore dùng `pg_restore --exit-on-error` và tar vào container mới chưa start. Tar được kiểm đường dẫn/loại entry; không có lệnh xóa serving data/volume. Đây là diễn tập local có writer freeze, không là hệ thống backup production, HA, off-host backup hoặc RPO/RTO đại diện.

### Lỗi đã phân loại và thay đổi cần thiết

- Fixture Volume limit thử nghiệm 4 làm Master hết writable volume, S3 PUT 500. Chỉ ba Volume fixture được đưa về giới hạn 32 của Compose hiện có, giữ named data; không đổi Platform. Fixture không còn tmpfs-only để chứng minh durability.
- `node_modules` từng là junction sang worktree khác khiến Turbopack từ chối filesystem root. Gỡ **link** đã xác minh (không xóa target), cài đúng lock bằng `npm ci --ignore-scripts`; worktree dependency độc lập. Offline cache thiếu Playwright package được phân loại môi trường và tải đúng lock, không bỏ build.
- Các lỗi selector/harness (mobile New trong navigation, tên Manage access, attachment không luôn phát page request event, API upload status không trả file_id, capability 404 có chủ đích, internal binding lookup khác public API) được sửa theo source contract. Không tính lượt fail/timeout là PASS, không đổi business logic/quota/security. Hai golden fixtures Next cũ được lưu evidence rồi dọn exact owner/key/size/SHA để chạy lại trong quota 10 MiB giữ nguyên.
- Audit phát hiện Next 16.3.3 critical/high. Vá cùng dòng 16: Next + eslint-config-next **16.4.6**, sharp **0.35.5**/libvips đi theo dependency chính thức, source-map-js **1.2.2**; Zod dev **4.6.7** tương thích (bản vá tối thiểu 4.6.6). Không thêm runtime dependency, không `audit fix --force`/downgrade ESLint config. [Next release](https://github.com/vercel/next.js/releases/tag/v16.4.6), [Next advisory](https://github.com/vercel/next.js/security/advisories/GHSA-673q-mjm6-r5xr), [sharp advisory](https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw), [source-map-js patch](https://github.com/7rulnik/source-map-js/releases/tag/v1.2.2), [Zod advisory](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5).
- **Dependency security OPEN:** audit production `--omit=dev` **0 findings**. Full audit sau patch còn **16 findings (10 high, 6 moderate)** thuộc dev lint/glob toolchain, gồm picomatch/brace-expansion/minimatch và dependency chains. Không tuyên bố full audit sạch. Thử update tương thích theo tên không đổi brace-expansion đang bị giới hạn bởi parent; không ép major override. [Picomatch chưa có patched version](https://github.com/advisories/GHSA-fc5q-39xc-vjpf), [minimatch fix ở 11.0.1](https://github.com/advisories/GHSA-g3hv-75wg-m249). Chỉ dùng source/pattern tin cậy trong toolchain; cần theo dõi bản vá upstream/đánh giá thay đổi tương thích trước production release. Không tự chấp nhận rủi ro thay operator.

Public paths thay đổi trong lượt này: `frontend/package.json`, `frontend/package-lock.json` (bản vá bảo mật); `frontend/e2e/p4-qualification.live.spec.ts` (real UI fixture); `frontend/e2e/workspace-upload.spec.ts` (private auth-state selector, mobile navigation, native download); `frontend/e2e/README.md`, `MAP.md`, tài liệu này (commands/version/evidence). Không thay module nghiệp vụ hoặc workflow để bỏ tests. Giữ nguyên original worktree và 20 EXCLUDE, gồm `.vscode/settings.json`.

### D — Operational consistency chỉ đọc

Platform 8 container healthy, Filer/4 Volume HTTP 200, Filer PG 17.11 reachable và 50 rows, application PG 18.6 riêng reachable read-only. **Volume thứ tư là mở rộng có khai báo**, không còn chỉ suy drift từ base Compose: runtime Compose labels dẫn cả `compose.yml` và private `.local/platform-nodes.compose.yml`; registry `.local/platform-nodes.json` liệt kê `extra_nodes=[volume4]`, named volume riêng cùng ownership/project, tạo 13/11/2026 03:52:15 UTC. Không xóa node hoặc sửa base Compose cho bằng số runtime.

Collector hiện có đã đọc extra-node registry; manual `collect()` read-only nhận đủ tám containers, gồm volume4. Không có monitoring source bug cần sửa. Capacity của Docker filesystem chung khoảng 1.081 TB, available 1.021 TB tại sample; không cộng thành tám ổ đĩa độc lập hoặc suy HA. Manual sample mới giữ private; không ghi đè metrics phục vụ để che sample cũ quá hạn (>60 giây). Serving telemetry freshness vẫn **STALE/Unknown**. Không thấy process CLI finalizer phục vụ theo pattern đã kiểm và không có heartbeat đáng tin cậy: **liveness Unknown**, không khẳng định mọi kiểu worker đều vắng mặt.

Serving aggregate chỉ đọc: uploads available 1/failed 1; jobs done 1/failed 1; reservations consumed 1/released 1; probes succeeded 1/cleanup_pending 1; connections ready 1/failed 1. Không retry cleanup trên tài nguyên này. Enterprise Lab cũ vẫn stopped. Reachable/healthy/record READY không thay qualified hoặc recoverable.

### Bàn giao, recovery và điều kiện P5

**Local:** PLATFORM FIXTURE QUALIFIED; ENTERPRISE FIXTURE QUALIFIED; FULL APPLICATION E2E VERIFIED; PERSISTENCE VERIFIED; OUTAGE RECOVERY VERIFIED; BACKUP/RESTORE VERIFIED. Ba gate A/B/C đạt **P4 development qualification** trong phạm vi fixture ở trên. **SERVING RUNTIME VERIFIED = PENDING; PRODUCTION RELEASE ACCEPTED = NO.**

Đã dừng đúng web/worker/frontend và toàn bộ **32 container fixture nguồn + restore**. Giữ **32 named volumes**, 11 pinned files trong mỗi bản dữ liệu, backup/config/receipt có ACL private để operator review; không gọi đây là zero-object cleanup, không xóa volumes hoặc private recovery material. Workspace tests đã xóa file exact/archive empty Workspace; một Workspace rỗng của lượt mobile timeout còn trong fixture DB, không serving. Không có active finalizer job hoặc reservation chưa settled tại consistency point. Không restart/reconfigure serving services sau auto-resume đã duyệt.

Rollback source cần review và revert đúng commit P4; không tự rollback về dependency có advisory. Dữ liệu nguồn fixture vẫn giữ để so sánh/diễn tập lại, không tự start hai generation cùng pinned endpoint. Serving không cần data rollback vì không đổi. Không phục hồi signing key lịch sử hoặc thay AES/storage keys phục vụ.

**Git candidate:** chỉ bảy public paths kể trên, review diff/security/index trước commit; tiếp tục Draft PR #4, không merge/deploy. Baseline `b7933a3` có đủ ba CI jobs PASS; kết quả đó không đại diện candidate mới. SHA/Actions của candidate được ghi trong body/checks PR sau khi repository-safety/backend/frontend hoàn tất trên cùng SHA. Default CI vẫn 662 executed PASS + 22 provider SKIP dự kiến, enabled 72/guards 30/no-DB 2; phải đọc kết quả thật trước khi báo remote PASS.

P4 đã cung cấp prerequisite provider/isolation/persistence/restore cho P5 development khi CI candidate đạt và được review. P5 vẫn cần failure table/crash/stale worker/quota/cleanup theo roadmap; các giới hạn serving/production và dev-tool security ở trên vẫn mở. Không triển khai P5 trong nhiệm vụ này.
