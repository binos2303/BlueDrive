# P5 — File lifecycle integrity

Baseline `6c8b9a6f19f921858ee8007207c2d342375e8944` của Draft PR #5. Phạm vi development, với PostgreSQL test riêng và SeaweedFS fixture P5. Giữ architecture, provider, storage revision, RBAC, quota và định dạng mã hóa hiện có.

## State machine tại baseline

| Record | Transition thực tế | Điều kiện và recovery |
| --- | --- | --- |
| UploadSession | `initiated → uploading → verifying → scanning? → available` | Khởi tạo quan sát quota và multipart. Complete lưu manifest và job. Worker xác minh/staging rồi ghi File, version, location, quota và audit trong cùng transaction. `completed` là trạng thái thành công được các đường đọc/retry chấp nhận. |
| UploadSession | `initiated/uploading → canceled/expired/failed`, `verifying/scanning → failed` | Cancel và expiry không được đụng session đang finalize. Worker fail giữ mã lỗi scanner/quyền nếu đã lưu. Quota phải được trả đúng một lần. |
| UploadFinalizationJob | `pending → processing → done/failed`, `processing → pending` | Attempt tăng khi claim, reclaim sau 10 phút. Kiểm attempt ở DB milestones. Lỗi provider retryable giới hạn ba lần. S3 RPC đã phát đi có thể hoàn thành sau khi mất claim. |
| QuotaReservation | `reserved → consumed/released` | Khóa session, reservation và quota accounts. Replay cùng kết quả giữ nguyên counters. Re-reserve từ released chỉ cho upload còn active. |
| FileVersion | `pending/uploading/verifying/scanning/available/quarantined/failed/deleting/deleted` | Đây là enum, không phải tất cả đều có writer hiện hành. Multipart publication chèn trực tiếp `available` sau xác minh bytes. Delete hiện điều khiển StorageLocation trước khi xóa FileVersion và metadata. |
| StorageLocation | `pending/available → delete_pending → deleted/error` | Pin revision và VersionId tại publication. Physical delete và DB commit cần retry riêng. |

## Lỗi và phương án đã chọn

| Mức | Bằng chứng trước sửa | Xử lý |
| --- | --- | --- |
| Cao | Trigger deferred trong PostgreSQL trả `40001` tại COMMIT, sau khi câu INSERT đã chạy. Baseline ghi upload và job `failed` ở attempt 1. | Retry lỗi DB tạm thời trong ngân sách ba attempts, giữ staging và reservation. Dọn staging qua `on_commit` sau khi metadata, audit và quota commit. |
| Cao | Hai yêu cầu xóa cùng snapshot legacy trên baseline cùng báo đã xóa một file. RESTORE còn có thể thấy bản ghi Trash khi một version đã mất bytes do xóa một phần. | Ghi purge intent trước I/O và ngừng cấp bytes mới. Khóa lại File ở bước hoàn tất, chỉ giảm quota cho row còn tồn tại. Giữ purge intent, location và quota khi storage hoặc COMMIT lỗi. Các đường restore chung từ chối purge đang dở. |
| Cao | Source khóa lại quyền Workspace sau COPY nhưng chỉ kiểm revision/config một lần trước COPY. Các đường xóa folder có thể cascade sau khi snapshot nội dung đã cũ. | Kiểm lại quyền, folder và chính revision/config đã pin trước publication. Khóa folder trước khi xóa metadata, từ chối cascade khi cây đổi hoặc còn upload active. |
| Trung bình | Reclaim sau crash ở attempt 3 có thể cấp attempt 4. Cleanup baseline xét một số state/ref hẹp và có thể xóa receipt sau khi bỏ qua object. Abort có thể báo `canceled` sau hạn. | Chặn attempt 4. Cancel/expiry và quota cùng transaction. Cleanup giữ receipt khi xung đột ref hoặc lỗi provider, đối chiếu quarantine key có thể đã được copy trước lỗi DB. |

Purge intent tương tự đánh dấu kiện hàng đang được tiêu hủy trong kho. Hệ thống chặn giao lại kiện đó ngay khi bắt đầu, giữ phiếu theo dõi cho lần thử lại và chỉ chốt số dư sau khi xác nhận xong.

## Kiểm chứng theo gate

Môi trường development ngày 18–19/11/2026, application PostgreSQL test 18.6 có marker và DB UUID riêng, SeaweedFS 4.53 và PostgreSQL Filer 17.11 trong project `bluedrive-p5-lifecycle-platform`. Dùng đúng test bucket private, versioning và identity mới của P5. Cả hai lỗi baseline đã được tái hiện trên PostgreSQL riêng trước bản sửa.

| Gate | Bằng chứng |
| --- | --- |
| B1–B5 | Recovery suite kiểm job stale trước publication, trước và sau commit, hết attempt, pending/retry và scanner từ chối theo fixture. Hai ca live mới dùng COPY thật với PostgreSQL COMMIT lỗi và hai DB connections cho stale claim. Worker cũ không thể thay metadata, audit hay quota sau khi worker mới commit. Report đếm physical version dư tại key đã biết. |
| C | PostgreSQL chạy cạnh tranh thật ở Personal My Drive, Enterprise Employee My Drive và Business Workspace. Kiểm đúng quota account, một request thắng sát quota, idempotency cùng payload, từ chối payload khác, consume/release một lần. Real Workspace upload dùng đúng workspace budget và kiểm bytes sau finalize. |
| D | Quyền Workspace, Tenant, user active, folder Trash và revision disabled được kiểm trước publication. Binding mới thiếu READY fail closed. Pinned upload giữ revision ban đầu kể cả binding đổi hoặc routing flag tắt. Cleanup đã pin giữ đích gốc. Enterprise Employee quota và DB isolation được kiểm trên fixture. |
| E | Timeout giữ cleanup receipt. Exact key có reference ở state lỗi/deleting được bảo vệ. Quarantine theo key xác định từ upload khi DB chưa ghi nhận copy. Hash mismatch live giữ file ngoài trạng thái AVAILABLE. Scanner rejection là fixture, malware scanner thực chưa kiểm chứng. |
| F | Partial delete trên các version thật và lỗi `40001` khi COMMIT sau S3 delete giữ metadata/used quota, chặn restore và không phát audit thành công. Retry loại bỏ đúng metadata và chốt quota/audit một lần. Ca delete song song dùng hai DB connections riêng, I/O adapter giả lập để đồng bộ thời điểm. Hai ca real backend trong provider suite kiểm bytes đã pin và download/share/Trash qua API hiện có. |
| G | Gateway fixture được pause để đo read timeout, Filer fixture dừng/chạy lại khi Gateway vẫn chạy. Multipart phần đã ACK giữ nguyên sau recovery, HEAD chưa thấy object trước hoàn tất, retry tạo VersionId và SHA-256 đúng. Đã xóa version đã tạo trong ca outage. Hai probe đầu của harness thất bại ở đối chiếu multipart, probe cuối dùng cấu hình checksum giống ứng dụng và chia ACK/timeout thành hai part riêng. |
| H | Lease 10 phút, claim theo attempt, retry tối đa ba lần. Worker loop giữ nhịp mặc định 2 giây và sweep cleanup mỗi 60 giây. Worker tổng hợp lỗi bằng loại và đếm finalized/retrying/failed. Các bài fault đã ngắt ở mốc I/O và COMMIT, hoặc tạo worker invocation mới qua DB. Serving liveness, backlog và telemetry vẫn UNKNOWN trong P5. |

Adapter hiện có giữ version pinning, multipart checksum/size, terminal idempotency và staged publication. DB fencing giới hạn quyền commit, nên một COPY đã gửi vẫn có thể tạo version dư. URL đã cấp còn bị ràng buộc bởi thời hạn ký và sự tồn tại của version. Browser UI và transport không có thay đổi P5, bằng chứng full UI và Enterprise provider từ P4 giữ phạm vi riêng.

## Đối chiếu và rollback

- `python backend/manage.py report_upload_recovery <upload UUID> [--inspect-storage]` có chế độ chỉ đọc. Có thể phân loại metadata AVAILABLE thiếu version, candidate version chưa có tham chiếu ở key đã biết, terminal reservation, expired multipart, purge intent, pending locations và quarantine. Dùng đúng storage credential chỉ đọc khi vận hành. Bất kỳ trạng thái nào đọc trong lúc RPC đang chạy đều cần kiểm tra lại. Báo cáo theo upload được chỉ định, vì vậy key ngoài receipt/phạm vi này cần inventory riêng. P5 không xóa tự động theo kết quả report.
- Migration `files/0019_file_purge_intent` thêm cột nullable và check constraint. Test runner áp dụng lên các DB độc lập. Trước khi rollback code hoặc schema trên môi trường được phép, lấy backup và đối chiếu purge intents. Khi còn purge dở, dùng forward-fix hoặc hoàn tất retry theo đúng revision với operator review. Bỏ marker khi object đã bị xóa một phần có thể mở lại đường restore sai.
- Scope source gồm finalizer, routing, cancel/cleanup, adapter API exact versions, permanent-delete service và các API gọi qua service, migration, tests và MAP. Không đổi định dạng mã hóa hay dependency. Không vận hành migration database phục vụ.
- Phạm vi fixture chỉ gồm project P5 và PostgreSQL test P5. 21 file đang sửa của checkout gốc giữ nguyên SHA-256, trong đó có 20 EXCLUDE. Evidence P4, 32 named volumes P4 và backup private giữ để operator review. Cảnh báo dev dependency `picomatch` theo cùng disposition của Draft PR #5.

## Bàn giao

| Kiểm tra local | Kết quả |
| --- | --- |
| Các suite mục tiêu | 76 PASS gồm finalization, quota, routing, Trash, admin và self-service. Kiểm tra bổ sung sau đó đạt 37 PASS và 7 PASS cho nhóm cleanup/concurrency/expiry. Các nhóm có bài trùng nhau. |
| Cấu hình bật feature flags, guards | 72 PASS và 30 PASS. |
| Django system check, migration consistency, pip check | PASS trên test settings. |
| Hai provider classes live | 15 PASS, 0 SKIP. Các bài này chạy opt-in, độc lập với skip của CI mặc định. |
| Real Gateway/Filer fault probe | PASS trong lượt xác nhận cuối. Đối chiếu 85 key có receipt, abort 2 multipart từ probe trước, còn 0 object version, 0 multipart và 0 resource ngoài receipt. Giữ 5 volumes P5 mới và config/receipt private để review. |
| Full regression, frontend, source/index | Run và kết quả trên exact commit ở checks của Draft PR. Hai ca provider mới tăng số skip mặc định từ 22 lên 24. |

Nhánh `feature/p5-file-lifecycle-integrity` kế thừa `fix/p4-final-cleanup-security`. PR checks và phần nghiệm thu trong Draft PR ghi exact head SHA, kết quả Actions và phạm vi quyền review. P5 runtime verification cần bằng chứng riêng trên môi trường đích được phê duyệt. Production release và P6 nằm ngoài đợt này.

## Final security review · 19/11/2026

Review [Draft PR #6](https://github.com/binos2303/BlueDrive/pull/6) từ `a0be25f1d9a4954d724f28b5a188b1d537f542eb`. Kết quả lịch sử trên SHA đó là 674 PASS, 24 provider SKIP, 72 enabled fixtures, 30 guards và 15 PASS trên SeaweedFS fixture. Cả ba jobs đạt ở [run của PR](https://github.com/binos2303/BlueDrive/actions/runs/44356119634). Bằng chứng provider dùng đúng SHA và fixture đã ghi ở trên.

| Mức | Finding | Bằng chứng và xử lý |
| --- | --- | --- |
| Cao, tính toàn vẹn và khả năng phục hồi | `finish_folder_purge` bỏ sót `UploadSession.State.AVAILABLE`, trạng thái thành công do finalizer ghi. API xóa cây sau khi upload có thể trả 503 dù đã gọi xóa object và đánh dấu File đang purge. Retry cùng yêu cầu tiếp tục bị chặn bởi lịch sử upload. | `test_purge_tree_with_published_upload_detaches_history_after_storage_delete` trên baseline trả 503. Sau sửa trả 200, xóa đúng object một lần, giữ lịch sử upload terminal, gỡ quan hệ với folder/File đã xóa và ghi đúng một audit thành công. |
| Cao, thứ tự preflight | Một upload thực sự còn active trong cây cũng chỉ được phát hiện sau I/O hủy object. Khi đó File có purge intent và restore bị chặn mặc dù điều kiện xóa thư mục đã có thể kiểm trước. | `test_purge_tree_with_active_upload_stops_before_deleting_objects` trên baseline quan sát adapter gọi delete. Bản sửa kiểm các folder đã chọn trước intent và I/O, vẫn kiểm lại trước xóa metadata. Sau sửa 503 giữ FileVersion, không đặt intent và không gọi adapter. |

Hai bài dùng PostgreSQL độc lập với marker/UUID và mock adapter để quan sát thứ tự I/O. Baseline **2 FAIL**. Sau sửa **50 PASS, 0 SKIP** cho collaboration, purge recovery, download security, admin files và self-service. Django system check và migration consistency **PASS**. Kết quả full regression và ba job của SHA sửa nằm trong [checks của PR #6](https://github.com/binos2303/BlueDrive/pull/6/checks). Hai bài mới không đo outage hay khả năng provider.

| Bất biến rà soát | Bằng chứng trong source và test |
| --- | --- |
| Xác minh bytes trước publication | `finalize_uploads` kiểm multipart ownership, size, SHA-256 và scanner nếu cấu hình. `finalization` công bố File/Version/Location cùng quota và audit. Tests mismatch và streaming giữ trạng thái chưa AVAILABLE khi bytes chưa đạt. |
| Claim, COMMIT, retry và quyền | Khóa và kiểm lại attempt, Tenant/Workspace membership, folder và revision đã pin trước ghi metadata. `on_commit` giữ staging qua rollback. Tests lỗi COMMIT, worker mất claim và hết ngân sách chứng minh không ghi trùng. COPY đã gửi vẫn có thể tạo version vật lý dư. |
| Purge, restore và accounting | Intent được ghi trước I/O trên các entry point dùng transaction riêng. Restore kiểm intent, adapter giữ đúng revision, các cleanup checks giữ object có tham chiếu ngoài tập xóa. `_finish_purge` khóa lại File còn tồn tại, đảm bảo location đã xử lý rồi commit quota/audit/xóa metadata. Tests partial delete, lỗi COMMIT và hai request overlap vẫn là bằng chứng riêng. URL phát hành trước intent chịu TTL và tình trạng object version. |
| Reconciliation | `report_upload_recovery` đối chiếu chỉ đọc theo key/version đã biết. Kết quả trong lúc RPC đang chạy có thể đổi. Chỉ báo cáo và giữ receipt khi ownership/ref hoặc độ đầy đủ của inventory còn nghi vấn. |

Migration `0019` vẫn additive, nullable và không có data migration. Trước rollback ở môi trường được duyệt, xác minh backup và lịch chặn writer gồm yêu cầu purge mới, xác định số File còn intent hoặc location đang xóa/lỗi, rồi đối chiếu theo đúng revision. Giữ schema và forward-fix hoặc hoàn tất retry cho đến khi các intent được xử lý. Chỉ xem xét đảo schema sau khi kiểm đường restore và xác nhận không còn purge dở. Review này kiểm migration consistency và forward từ test runner, chưa chạy reverse trên dữ liệu phục vụ.

Serving finalizer, malware scanner thật và runtime acceptance vẫn có phạm vi nghiệm thu riêng. Trạng thái bucket/volumes P4–P5 và recovery material được giữ theo disposition đã ghi.
