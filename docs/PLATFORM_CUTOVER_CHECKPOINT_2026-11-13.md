# Platform SeaweedFS — checkpoint trước ghi dữ liệu thật

Ngày **13/11/2026**, Asia/Bangkok. Tiếp nối [báo cáo chuẩn bị](PLATFORM_CUTOVER_REVIEW_2026-11-12.md) và [ADR-0008](ADR-0008-platform-storage-copy-and-publication.md).

Checkpoint này giữ nguyên bằng chứng trước khi sửa qualification. Theo dõi kết quả và điều kiện mới tại [qualification runtime 13/11](PLATFORM_QUALIFICATION_2026-11-13.md); các số liệu bên dưới không tự thay bằng trạng thái mới.

**Kết luận: NO-GO cho copy/publish/routing hiện tại.** Đã có revision thật, manifest dự kiến và backup mới; full qualification của revision bị chặn bởi quyền LAB probe. Không áp dụng migration vào DB phục vụ, không copy/publish FileVersion thật, không đổi binding/routing và không dừng MinIO.

## Trước và sau công việc lần này

| Hạng mục | Trước | Sau |
| --- | --- | --- |
| Working tree | 262 status entries, 219 untracked | Giữ toàn bộ thay đổi cũ; chỉ thêm/sửa phần checkpoint và plan-only |
| Platform cluster/revision | 0 / 0 | 1 / 1, đăng ký qua service hiện có |
| Actor audit | Chưa chọn | Người dùng chọn `bluedrive_admin`, ID 5 |
| Revision | Chưa có | Read check PASS, LAB probe bị từ chối; state hiện tại `failed`, không giả `ready` |
| Platform binding / routing | 0 / OFF | 0 / OFF |
| `infrastructure.0006` DB phục vụ | Chưa áp dụng | Chưa áp dụng; diễn tập trên restore DB riêng PASS |
| FileVersion / location nguồn | 31 / 31 MinIO | Không đổi; 31/31 bytes/SHA-256 khớp |
| FileVersion migrate/publish thật | 0 | **0/31** |
| Config/credential/key nguồn | Hiện hữu | Hash backend/Platform/Enterprise private config không đổi |

Việc đăng ký/read-check và probe là metadata cấu hình được yêu cầu ở bước 4, không phải chuyển nơi phục vụ. ClusterAuditEvent ghi đúng actor 5. Không stage/commit/push, reset/stash hoặc xóa source.

## Revision và gate thực tế

- Cluster: `f3ae021f-e3bb-4ba2-a0e7-d1991a6de0cf`, kind **platform**, provider **s3**.
- Revision 1: `3bd9b5d0-8dfb-4b15-8b4f-41d77b54958a`.
- Profile: `platform-seaweedfs-v1`; internal `http://127.0.0.1:8333`, public `http://s3.localhost:8333`, bucket `bluedrive-dev`, network `127.0.0.1/32`.
- Profile/secret alias chỉ được nạp trong process đăng ký/kiểm tra. Chưa thay registry/flag của web/worker. Credential dùng lại identity ứng dụng hiện có, tên tham chiếu `BLUEDRIVE_PLATFORM_S3_ACCESS_V1` / `BLUEDRIVE_PLATFORM_S3_SECRET_V1`; không lưu giá trị vào profile/manifest.
- Signed HEAD, bucket versioning và CORS: **PASS** bằng chính identity ứng dụng.
- TLS / configured SSE: **false** theo môi trường local HTTP/LAB hiện có; không chứng nhận production security/HA.

Probe `418a7548-b03d-43b8-b49f-5763a63c5d4f` chạy đúng `begin_probe`, nhận `storage_identity_rejected` tại quyền bucket tạm. Quy trình S2 yêu cầu cùng identity tạo/tag/version/CORS/xóa bucket `bluedrive-scc-<probe UUID>`, trong khi identity runtime giới hạn data bucket. Không sửa policy bucket hoặc cấp thêm quyền để ép pass.

`bucket_created=false`; operator hiện có kiểm tra và xác nhận fixture **không tồn tại**. DB probe vẫn `cleanup_pending` vì reconciler của profile ứng dụng không có quyền HEAD namespace đó. Đây là pending metadata cần xử lý bằng quy trình đã duyệt, không có bucket/object fixture bị bỏ lại. Không update SQL để giả completed/ready và không đổi credential của revision trong lúc probe.

Giống kiểm kho bằng thẻ nhân viên: thẻ đọc/ghi trong kho chính đã được xác minh, nhưng bài kiểm định hiện đòi thêm quyền mở một kho tạm. Dùng chìa khóa tổng để vượt bài kiểm rồi giữ quyền đó cho runtime không chứng minh quyền hạn chế ban đầu.

**Khuyến nghị:** giữ identity runtime hạn chế và chuẩn bị gate fixture có receipt trong bucket đã được duyệt, kiểm PUT/GET/browser/version/SHA/cleanup bằng cùng identity. Đây là mở rộng quy trình qualification cần review trước triển khai, chưa được viết hoặc kích hoạt trong lần này. Nếu operator chọn giữ nguyên probe LAB, phải review riêng thay đổi IAM LAB có giới hạn và rollback; không mặc định cấp quyền quản trị bucket cho runtime. Không có action copy/routing nào đủ điều kiện duyệt khi gate này chưa đóng.

## Inventory và 48 tham chiếu

| Kiểm kê mới | Kết quả |
| --- | --- |
| Source | MinIO `http://127.0.0.1:9000`, bucket `securedrive-files` |
| File/FileVersion/StorageLocation | 31 / 31 / 31 |
| Full SHA-256 và bytes | **PASS 31/31**, 5.693.666 byte |
| Tags/source versioning | 31 version tags rỗng; versioning Enabled |
| Multipart source (operator LIST mới) | **0**; identity app vẫn AccessDenied, không suy Unknown thành 0 |
| Upload đang hoạt động / job pending-processing / reservation reserved | **0 / 0 / 0** |
| Finalization job | 46 done |
| Reservation lịch sử | 48 consumed, 6 released |
| Share / ActivityLog / QuotaAccount | 2 / 242 / 19, giữ nguyên |
| Staging versions / unreferenced candidates | 0 / 0 trong source LIST hiện có |

48 session legacy đều còn **chỉ `final_object_key`**: `object_key=0`, `provider_upload_id=0`. Có 31 final key đang được location nguồn tham chiếu; 17 session không còn file/location, là lịch sử đã tháo FK. Theo eligibility hiện tại của `cleanup_uploads`, final-key-only của session published không phải việc cần abort/xóa staging. Không chạy cleanup toàn cục hoặc xóa 48 key để làm sạch báo cáo; giữ quota/session/audit history. Sau cutover, 31 source locations vẫn là đường rollback và permanent-delete vẫn có thể dùng MinIO, nên chưa được decommission.

## Chuẩn bị tạm dừng ghi

Snapshot process: không thấy Django web/finalizer trên host, không listener 3000/8000; chỉ thấy storage loopback 8333/8433/9000. Docker có đúng năm Platform service healthy, Enterprise riêng và MinIO còn chạy. Không có process bị tự dừng/restart trong công việc lần này.

Snapshot không phải khóa chống process khác khởi động. Trong cửa sổ được duyệt:

1. Chặn traffic ghi ở entry point, ngăn supervisor khởi động lại writer; dừng đúng web/finalizer được nhận diện. Không stop storage/Enterprise.
2. Đợi upload/job/reservation drain; kiểm multipart bằng operator. Chờ ít nhất **300 giây sau lần cuối cấp URL PUT** theo presign max hiện tại; không chỉ chờ đồng hồ rồi tự coi writer đã dừng.
3. Chụp process/container và inventory lần cuối; xác nhận không có writer trực tiếp S3 ngoài phạm vi. Khóa PostgreSQL của publication không khóa S3 writer bên ngoài.
4. Lập lại manifest nếu fingerprint nguồn đổi; backup DB/object phải khớp inventory đã đóng băng. Approval hiện có `writers_stopped=false` và không cấp action nào.
5. Khi đã duyệt và đủ gate, giữ global MinIO cho legacy trong lúc chọn binding SeaweedFS cho upload mới; web/worker phải cùng version/profile/env alias. Không chép đè `.local/backend.env` lên cấu hình nguồn.

Không thêm middleware/service/dependency chỉ để thay thao tác bảo trì. Chưa tuyên bố hệ thống đang trong frozen window.

## Manifest và thao tác dự kiến

Thư mục private, ignored: `infra/seaweedfs/.local/cutover-preflight-20261113-a0651624d265/`.

| Artifact | Vai trò |
| --- | --- |
| `cutover-plan.json` | Exact 31 source→key/location đích, snapshot và target revision thật |
| `dry-run-summary.json` | Số lượng, bytes, SQL digest và execution gate |
| `inventory.json`, `operator-source-metadata.json` | Inventory DB/S3 và metadata source hiện tại |
| `revision-registration.json`, `lab-probe-result.json`, `profile-v1.json` | Registry/read-check/probe; không chứa secret hoặc URL ký |
| `cleanup-references.json`, `process-snapshot.json`, `containers.json` | Phân loại lịch sử và chuẩn bị freeze |
| `migration0006.sql` | SQL đúng code hiện tại để operator review |
| `approval-draft.json` | **DRAFT_NOT_AUTHORIZED**, `actions=[]`, `writers_stopped=false` |

Plan SHA-256: **`afb72682b89a6024b39e9b2ef2d0815c2a2f6c3015d7444018a5b7c744addf50`**.

Manifest file SHA-256: `915b54a47f8cc43997a5f392be201037093295465adaf41b92bc7c237456f0b8`.

Plan hiện tại dùng `--allow-unverified-target` sau read check thật. Cờ chỉ dành cho `plan`, ghi `qualification_at_plan`; mọi copy/publish vẫn gọi `_target(require_ready=True)`. Đã thử gate validation: **BLOCKED_NOT_READY**, không PUT, không tạo location. Không được xem plan này là quyền thực thi.

Sau khi gate/approval được đáp ứng, dự kiến:

- Apply đúng **một migration** `infrastructure.0006_allow_deleted_upload_history`; không backfill dữ liệu file, không có migration khác trong plan.
- Copy 31 object / 5.693.666 byte sang key xác định `primary/<uuid5>` trong target bucket, giữ user metadata; target VersionId phải lấy từ response thật và GET/SHA-256 lại. Chưa có VersionId đích để ghi trước.
- Tạo tối đa **hai StorageConfig S3** còn thiếu theo hai tenant có dữ liệu; thêm **31 StorageLocation**. Giữ nguyên 31 source locations, FileVersion, sharing, reservation và quota.
- Publish transaction additive, kiểm selector cuối cùng; không tạo thêm version logical hoặc consumed quota lần nữa.
- Chuẩn bị binding Platform generation 0→1 theo API hiện có; chỉ bật routing trong cửa sổ được duyệt, sau khi web/worker nạp đúng profile/credential alias. Không tự bật direct-download hoặc cờ khác.
- Chạy app live My Drive/Personal Workspace/Finalizer/quota/sharing/trash/restore/audit trước khi đề xuất kết thúc maintenance. Hiện chưa có app E2E sau cutover, không dùng các bài mocked lịch sử để thay thế.

## Backup, migration rehearsal và rollback

Backup source đã có được đọc lại trên disk và đối chiếu với inventory mới: **31/31**, bytes và user metadata khớp; AES runtime key khớp backup trong bộ nhớ, không xuất key. Evidence `backup-revalidation.json`.

Backup DB mới sau đăng ký revision nằm dưới ACL backup hiện có:

`backups/platform-cutover-20261112-8f5de27c-verified/preflight-20261113-a0651624d265/`

| Gate mới | Kết quả |
| --- | --- |
| Custom dump | 315.062 bytes; SHA-256 `99e394069e597534af488c2b118362e30821117bff534566d481e754f50ce8b9` |
| Restore ngẫu nhiên cách ly | **PASS**, 51 bảng / 982 hàng khớp fingerprint |
| Constraint/trigger | **PASS**, 688 constraints, 27 canonical CHECK round-trips, custom triggers khớp |
| Apply `0006` trên restore DB | **PASS**; các bảng nghiệp vụ không đổi, chỉ migration recorder/function thay như dự kiến |
| Source migration/function | Kiểm tra lại **chưa áp dụng/không đổi** |
| Dọn restore DB | **PASS**, chỉ DB test do tác vụ tạo |

SQL migration SHA-256: `86f0cb931056743d67a553b0c06ca427b550dece4aba6af29e5cc6221501f9ab`.

Diễn tập DB và S3 recovery 31 object từ lượt trước được hash-kiểm chứng lại, không chạy lại test đã đạt để thay bằng con số mới. Backup vẫn local, chưa có độ bền off-host hoặc snapshot DB/S3 chung sau khi freeze.

Rollback vận hành ưu tiên dừng writer, giữ code đọc revision; `rollback` kiểm lại nguồn rồi chuyển target location đúng manifest về pending. Không xóa object đích/nguồn. Global MinIO/credential/key được giữ. Rollback lô cũ không chuyển ngược file mới đã ghi lên SeaweedFS, nên phải giữ kho đích và reader cho chúng. Sau khi có terminal history tháo FK, không reverse `0006`; dùng forward-fix theo ADR. DB restore nguyên khối cần đánh giá các ghi phát sinh sau backup, không restore đè tự động.

## Kiểm tra code và điều kiện phê duyệt

Thay đổi source mới chỉ mở rộng plan-only, không viết lại adapter/worker/tests đã đạt:

- `backend/files/storage_cutover.py`
- `backend/files/management/commands/migrate_platform_storage.py`
- `backend/files/tests/test_storage_cutover.py`
- `infra/seaweedfs/README.md`, `docs/ADR-0008-platform-storage-copy-and-publication.md`, `MAP.md`, báo cáo này.

**PASS 25/25** tests mới chạy bằng runner DB riêng: storage cutover + audit, 0 skip/fail. Có case mặc định đòi ready, cờ chỉ cho plan, read-check bắt buộc, copy vẫn bị chặn và manifest không đổi khi cố bypass. Các kết quả 601/106 backend, 159 Node/212 mocked browser và recovery trước đó giữ đúng ngày trong báo cáo cũ, không tính thành kết quả chạy mới.

Kiểm tra bàn giao mới: Django check **PASS**, migration consistency **PASS** (No changes detected), AST/link/whitespace cho bảy file scoped và `git diff --check` **PASS**. Repository safety **PASS**: 633 text files, một binary chưa scan, không findings/blocked; không phải chứng nhận scanner đầy đủ hoặc runtime acceptance.

Checkpoint yêu cầu operator review **NO-GO và phương án đóng gate qualification trước**, rồi mới duyệt cửa sổ migration/final inventory. Không có approval copy/publish/routing hợp lệ được tạo. Không thể chỉ phê duyệt manifest rồi bỏ qua probe failed/pending hoặc xác nhận writer bằng suy đoán.

| Trạng thái bàn giao | Kết quả |
| --- | --- |
| Metadata revision đã đăng ký | **CÓ** |
| Signed read/versioning/CORS | **PASS** |
| Full revision qualification | **BLOCKED** bởi IAM LAB probe |
| Migration0006 restore rehearsal | **PASS**; DB phục vụ chưa áp dụng |
| Manifest/dry-run | **CÓ, plan-only**; execution gate chặn đúng |
| RUNTIME CUTOVER COMPLETE | **KHÔNG**, source reads vẫn MinIO |
| DATA MIGRATION VERIFIED | **KHÔNG**, migrate/publish **0/31** |
| MINIO DECOMMISSION READY | **KHÔNG**, không có thành phần runtime nào được phép gỡ tại checkpoint này |

Sau nghiệm thu runtime có thể bổ sung case qualification theo identity hạn chế và checkpoint này vào skill `bluedrive-storage-validation`; không tạo skill trùng runbook.
