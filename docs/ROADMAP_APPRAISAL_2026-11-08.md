# BlueDrive — Thẩm định kiến trúc và roadmap trước triển khai

Ngày: 08/11/2026. Tài liệu được thẩm định: `C:\Users\dang2\Downloads\BlueDrive_NghienCuu_KienTruc_Roadmap_2026-11-08.md`.

## 1. Kết luận

**Chấp thuận hướng tổng thể có điều kiện.** Giữ Next.js + Django + PostgreSQL + MinIO, ưu tiên khả năng phục hồi và tính đúng đắn trước mở rộng tính năng là phù hợp. Roadmap cần được cập nhật theo implementation hiện tại trước khi chuyển thành backlog triển khai.

Các điều chỉnh quan trọng:

1. Tái sử dụng `UploadFinalizationJob`, `QuotaReservation`, kiểm tra checksum, VersionId và cleanup hiện có. Chưa có lý do tạo ngay một outbox hoặc quota ledger khác.
2. Đưa kiểm tra quyền/trạng thái Workspace tại bước publication và phục hồi job sau crash lên đầu danh sách sửa. Có tình huống tái hiện được, vượt khỏi mức giả thuyết chung trong roadmap.
3. Xử lý N+1 và hợp đồng phân trang trước chiến dịch benchmark metadata lớn. Fixture 10 file đã phát sinh 116 SQL, 30 file phát sinh 313 SQL.
4. Thiết kế benchmark theo giới hạn hiện tại **100 MiB/file**, part 8 MiB và concurrency thực tế. Kịch bản 1 GiB/10 GiB thuộc một thay đổi giới hạn sản phẩm riêng.
5. Giữ TLS/SSE/scanner/backup như các gate trước production, nhưng ghi nhận code đã có một số guard. Cấu hình yêu cầu SSE không thay thế bằng chứng provider đã mã hóa object.
6. Đưa telemetry tối thiểu, kiểm thử tự động và runbook phục hồi lên sớm. Chứng minh vận hành cần diễn ra trong quá trình xây dựng các luồng dữ liệu.
7. Hoãn sync client, change feed, CDC/dedup, E2EE và HA phức tạp cho đến khi có nhu cầu sản phẩm, dữ liệu đo và khả năng bảo trì phù hợp.

Ví dụ thực tế: hiện đã có quầy tiếp nhận, sổ giữ chỗ và xe giao hàng. Việc cần làm trước là kiểm tra quyền ở cửa bàn giao, xử lý đơn đã giao nhưng sổ còn ghi thất bại, rồi đo chỗ xếp hàng. Xây thêm một quầy và một cuốn sổ song song sẽ tăng nguy cơ hai nơi ghi khác nhau.

## 2. Phạm vi và bằng chứng

Đã đọc các phần source trọng yếu của upload/finalize, job recovery, quota, download, storage adapter, tree traversal, listing, ZIP, resume phía trình duyệt và cấu hình Django. Đã kiểm tra nguồn học thuật chính, tài liệu AWS S3/outbox, OWASP ASVS, PostgreSQL và Seafile.

Đã chạy **39 test chọn lọc, tất cả đạt**: 6 probe chẩn đoán mới và 33 regression test hiện có về finalization, Workspace quota và presigned download. Probe dùng PostgreSQL test riêng, media tạm, email trong bộ nhớ và storage giả lập. Database test đã được hủy sau chạy. **Một probe đạt có thể có nghĩa nó đã chứng minh hành vi không mong muốn đang tồn tại**, không có nghĩa hành vi đó đạt chuẩn sản phẩm.

Lượt này không sửa application source, migration, policy bucket, dữ liệu/tài khoản thật hay tài liệu roadmap gốc. Chỉ tạo báo cáo và artifact chẩn đoán. Không chạy lại toàn bộ 405 test, benchmark tải cao hoặc fault injection lên worker/MinIO đang phục vụ local. Kết quả 405 backend, 152 unit, 156 browser và 5 live test trong báo cáo trước là bằng chứng của lượt rà soát trước.

Source được đối chiếu ở working tree đang có thay đổi chưa commit; HEAD là `d968ebffa0d17f4fce81c2b2f56af5021e60e070`, không đại diện đầy đủ cho các byte đã thẩm định. Manifest SHA-256 của 19 file trọng yếu nằm trong `frontend/test-results/roadmap-review/source-manifest.json`.

Skill: `ponytail` cho KISS/DRY/YAGNI và đối chiếu caller/constraint trước đề xuất; `impeccable` cho việc thẩm định mục tiêu UX/khả năng truy cập và phân biệt bằng chứng implementation với nghiệm thu trực quan. Không chấm lại điểm UX trong lượt này.

## 3. Những hạng mục đã có và cần tái sử dụng

| Hạng mục roadmap | Trạng thái source hiện tại | Kết luận thẩm định |
|---|---|---|
| Durable dispatch/outbox cho finalize | `complete_upload` đổi session sang verifying và tạo OneToOne job trong cùng transaction; hai lần complete chỉ có một job | Củng cố job hiện có. Chỉ thêm outbox tổng quát khi có thêm hệ quả độc lập như thông báo/change feed |
| Idempotent publish | Session có `file`, state, idempotency key và final object key được lưu trước S3 I/O; publication kiểm tra lại state dưới row lock | Có nền tảng. Cần thêm recovery/fencing, không triển khai lại từ đầu |
| Quota reserve/commit/release | `QuotaReservation` có unique `(upload_session, quota_account)`, row locks, state reserved/consumed/released và xử lý lặp | Dùng làm cơ sở accounting. Ledger append-only chỉ nên thêm nếu yêu cầu audit tài chính/lịch sử không được mô hình hiện tại đáp ứng |
| Checksum, MIME và ZIP validation | Worker tính SHA-256 trên stream; validator kiểm tra filename, nội dung và giới hạn ZIP | Đã có. Scanner malware là lớp riêng, hiện chỉ có hook tùy chọn |
| Tách network I/O khỏi transaction publication | Lưu final key trong transaction ngắn, thực hiện S3 copy/put bên ngoài, commit metadata/quota/audit sau đó | Đúng hướng, nên giữ. Không biến khuyến nghị “không giữ transaction khi truyền GB” thành một rewrite không cần thiết |
| Bounded verification memory | Worker dùng spool 8 MiB rồi tràn ra đĩa; publish multipart bằng S3-side copy | Đã có. Khi bật scanner hiện tại vẫn đọc tối đa cả file vào bytes; cần tính riêng chi phí scanner |
| Version-pinned direct GET | `StorageLocation.provider_version_id`, verified metadata và HEAD đúng version trước presign | Đã có cho file đủ điều kiện; không đồng nghĩa đã có UI version history/restore logical |
| Cleanup/reconciliation | `cleanup_uploads` xử lý session expired/canceled/failed và staging của available đã đến hạn; worker bù missing jobs/reset stale jobs; có quota migration command | Có các công cụ từng phần. Chưa thấy inventory/reconciler tổng quát đối chiếu mọi DB row ↔ object/version |
| TLS/SSE production guards | Khi `DEBUG=false` và cấu hình object storage, settings yêu cầu HTTPS, verify TLS và SSE hợp lệ | Đã có guard cấu hình. Chưa có bằng chứng provider encryption/KMS recovery end-to-end |
| Opaque object keys | Adapter dùng prefix server-owned + UUID hex và allowlist chặt | Giữ format hiện tại. Mẫu `tenants/.../files/.../versions/...` trong roadmap sẽ bị adapter hiện tại từ chối; đổi format cần compatibility plan |
| Upload resume | Có session ID/idempotency/part receipts trong localStorage, reconcile với provider và pause/resume | Có resume có điều kiện. Task queue và File handle vẫn ở bộ nhớ, chưa phải tự phục hồi toàn bộ queue sau refresh |
| ZIP download | Có giới hạn 500 file, 1.000 folder, 500 MiB tổng bytes và spool 8 MiB | Chưa cần biến mọi ZIP thành background job. Hàm đọc từng file vẫn materialize plaintext nên không được hứa RAM độc lập với file size cho ZIP |
| FileVersion/current version | Model + unique constraint cho một available current version đã có | Không thêm đồng thời `current_version_id` và `is_current` thành hai nguồn sự thật nếu chưa có ADR/migration rõ |
| UI hiện tại | Dùng shared components, light/dark tokens, selected Workspace và shared-folder context | Giữ thiết kế. Bổ sung kiểm chứng assistive technology/zoom, không cần redesign thương hiệu |

Vị trí chính: `backend/files/upload_api.py:600`, `backend/files/models.py:533`, `backend/files/quota.py:154`, `backend/files/finalization.py:83`, `backend/files/views.py:611`, `backend/files/management/commands/cleanup_uploads.py:17`, `backend/folders/archive_service.py:21`, `frontend/components/drive/upload-service.ts:263`.

Một outbox đúng nghĩa giải quyết việc lưu sự kiện bền cùng transaction và yêu cầu consumer xử lý lặp an toàn. Job finalize hiện có đã đáp ứng phần nền tảng đó cho một workflow cụ thể; việc cần mở rộng là semantics/recovery của nó. [AWS — Transactional outbox](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html).

## 4. Khoảng trống xác nhận được bằng probe

### D01 — Quyền Workspace chưa được kiểm tra ở bước publication

**Ưu tiên đề xuất: P1; cần xử lý trước release nếu chọn policy “quyền hiện tại tại lúc commit”.**

Đã tái hiện riêng hai tình huống:

- Editor reserve quota và upload đến verifying, sau đó bị đổi sang Viewer. `can_edit_workspace_content` trả false nhưng `finalize_verified_upload` vẫn tạo file available và consume quota.
- Workspace bị archive sau khi session đến verifying. Worker vẫn tạo file available.

Storage được mock; publication, metadata và quota là logic thật chạy trên PostgreSQL test. Đây là khoảng trống so với chính gate “validate ACL again” của roadmap, chưa phải bằng chứng truy xuất chéo tenant hoặc file đã bị lộ ra ngoài. Quyền xem của Workspace archived vẫn là một ranh giới riêng.

`complete_upload` có kiểm tra quyền trước khi nhận complete, còn `finalize_verified_upload` chủ yếu kiểm tra session state. Quota completion kiểm tra active tenant membership, không thay thế kiểm tra Workspace role/status. Xem [finalization.py](C:/Users/dang2/Project/SecureDrive/backend/files/finalization.py:121), [upload_api.py](C:/Users/dang2/Project/SecureDrive/backend/files/upload_api.py:579), [quota.py](C:/Users/dang2/Project/SecureDrive/backend/files/quota.py:163).

**Khuyến nghị:** ghi rõ tác động của downgrade/archive lên upload đã nhận; nếu yêu cầu hủy quyền ghi đang chờ, kiểm tra lại trước publication và trong bước commit ngắn, có serialization phù hợp với thay đổi quyền. Khi từ chối phải quyết toán reservation và cleanup an toàn. Cần test thay quyền trước copy, giữa copy/commit và sau commit; không chỉ thêm một kiểm tra rời rồi coi mọi race đã được giải quyết.

### D02 — Recovery job có thể báo failed cho file đã available

**Ưu tiên đề xuất: P1 cho tính đúng đắn vận hành.**

Probe mô phỏng crash sau commit publication nhưng trước khi job chuyển DONE: file available, staging đã xóa, job PROCESSING cũ hơn 10 phút. Lượt recovery reset job rồi thử complete multipart lại; staging không còn dẫn đến job FAILED trong khi file vẫn AVAILABLE.

Không mất file trong probe. Rủi ro được chứng minh là trạng thái job sai và tín hiệu thất bại gây hiểu nhầm. [finalize_uploads.py](C:/Users/dang2/Project/SecureDrive/backend/files/management/commands/finalize_uploads.py:117) lấy stale jobs rồi đi vào S3 I/O trước khi đối soát session đã terminal thành công.

**Khuyến nghị:** terminal success của session phải giúp job hội tụ về DONE mà không complete/download staging lại. Thêm test crash ở hai phía của commit và quota exactly-once. Giống đơn hàng đã giao: hệ thống cần sửa lại sổ giao hàng thay vì tìm lại kiện hàng trong kho xuất.

### D03 — N+1 được đo ở fixture nhỏ

**Ưu tiên đề xuất: P1 cho kế hoạch mở rộng; chưa gán kết luận về p95/p99.**

| Probe | Số mục/node | Số truy vấn SQL |
|---|---:|---:|
| GET `/drive/api/items/?view=drive` ở Workspace | 10 file | 116 |
| Cùng endpoint, cùng role, tăng dữ liệu | 30 file | 313 |
| `folder_subtree`, root + 12 folder con | 13 folder | 13 |

Đây là query-count qua Django test client và `CaptureQueriesContext` trên PostgreSQL. Bao gồm chi phí request/auth ở listing; không phải đo tải production, không suy tuyến tính các con số này thành latency ở 100k file.

Source listing materialize cả danh sách ở nhánh thường và gọi permission theo từng mục; tree helper hỏi children riêng cho mỗi node. Xem [dashboard/views.py](C:/Users/dang2/Project/SecureDrive/backend/dashboard/views.py:367), [tree_service.py](C:/Users/dang2/Project/SecureDrive/backend/folders/tree_service.py:14).

**Khuyến nghị:** profile query lặp; tái sử dụng thông tin role/membership trong phạm vi một request, preload quan hệ cần thiết và giữ ngoại lệ direct share. Không dùng cache ACL toàn cục gây chậm hiệu lực revoke. Thêm phân trang/sort server có hợp đồng với UI. Đối với cây, so sánh batch theo frontier với recursive CTE trên cây rộng/sâu và giữ scope/cycle guard. Chưa có cơ sở đưa Redis, closure table hay search engine mới vào ngay.

### D04 — Multipart tuning cần thay đổi protocol trước

**Ưu tiên đề xuất: điều kiện thiết kế trước Phase hiệu năng.**

Part size 8 MiB được ghi riêng ở ba nơi: `upload_api.py:34`, `finalize_uploads.py:30`, `upload-service.ts:64`. Response create có `part_size` nhưng client tiếp tục cắt file/reconcile bằng hằng số; session chưa lưu part size riêng.

Thay hằng số hoặc bật “adaptive part size” có thể làm upload đang chạy/resume bị diễn giải theo kích thước khác. **Khuyến nghị:** trước khi tune app, thiết kế part size bất biến theo từng session, do server cấp, được worker/client cùng dùng, có tương thích session cũ. Raw-storage benchmark có thể thử chunk size khác trong harness riêng nhưng không được gọi kết quả đó là hiệu năng ứng dụng end-to-end.

## 5. Các rủi ro cần đo thêm, chưa tái hiện thành lỗi

| Vấn đề | Bằng chứng hiện có | Việc cần chứng minh |
|---|---|---|
| Worker claim/lease | Job PROCESSING được reset khi `updated_at` cũ 10 phút, chưa thấy heartbeat, fencing token hoặc `skip_locked` | Hai worker, task lâu hơn lease, worker cũ tiếp tục chạy: không publish/cleanup xung đột |
| Retry/backoff | Có retry tối đa 3 lần cho storage retryable/IntegrityError; worker loop có interval | Thời gian retry, phân biệt poison input và outage dài, failure review có theo dõi |
| Reconciliation tổng quát | Có cleanup từng phần, quota migration và storage-location states | Inventory/version-aware audit; dry-run; referenced object không bị GC; scan/quarantine retention |
| Tính bất biến của audit | Có log trong transaction publication | Chính sách sửa/xóa, quyền truy cập audit, retention/export và khôi phục audit; chưa gọi là tamper-proof |
| Resume sau reload | Receipts lưu localStorage; queue/File handles ở ref/state | Chọn lại cùng file thì resume ra sao; tự khôi phục queue, đổi tài khoản và stale receipt phải có test riêng |
| File history/restore | Model version và storage VersionId có | Luồng tạo version logical mới, chọn restore, quota của lịch sử, hành vi Trash/purge chưa được chứng minh |

Những hàng này là backlog kiểm chứng, không phải kết luận đã có mất dữ liệu/deadlock hay exploit.

## 6. Đối chiếu runtime local và gate production

Đọc configuration chỉ xuất cờ an toàn; không xuất credential, cookie, key hay object reference:

| Mục | Quan sát trong lượt thẩm định | Kết luận được phép |
|---|---|---|
| Django | `DEBUG=true` | Đang xét môi trường phát triển |
| Storage endpoint | Đã cấu hình, scheme HTTP | Local chưa chứng minh TLS production |
| SSE yêu cầu từ app | Chưa cấu hình | Không có yêu cầu SSE tường minh từ app trong local |
| Bucket default encryption | GET bị AccessDenied với danh tính ứng dụng | **Chưa biết** provider có default encryption; không suy ra chắc chắn dữ liệu không được mã hóa |
| Bucket versioning hiện tại | GET bị AccessDenied | Lượt này không xác nhận lại bucket setting; bằng chứng VersionId thật ở lượt trước vẫn có giá trị tại thời điểm test trước |
| Scanner hook | Chưa cấu hình | Multipart local hiện không qua hook antivirus |
| Download TTL | 180 giây | Đây là giá trị local hiện hành, không chỉ là khoảng 60–180 giây đề xuất |
| PostgreSQL | 18.6, `wal_level=replica`, `archive_mode=off` | Continuous WAL archiving cho PITR chưa bật ở server local được hỏi; không phủ định một cơ chế backup ngoài hệ thống chưa được khảo sát |
| Query statistics | Chưa có extension `pg_stat_statements` trong database hiện tại | Có thể dùng EXPLAIN/query capture trước; bật extension là một thay đổi cấu hình riêng |
| MinIO edition/version | Compose ghi image `quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z`; Docker CLI không khả dụng trong phiên công cụ | Chưa xác minh binary/edition đang chạy. Tài liệu AIStor không tự động là capability matrix của binary này |

Giữ quyền runtime hẹp: **không cần cấp thêm GetBucketEncryption/GetBucketVersioning cho app chỉ để thuận tiện audit**. Kiểm tra quản trị nên thực hiện bằng danh tính operator và môi trường được kiểm soát khi triển khai Phase data safety.

Settings hiện có production guards HTTPS/SSE/TLS verify tại `backend/securedrive/settings.py:205`. Đặt biến cấu hình đúng vẫn cần được kiểm chứng bằng write → stat/read, provider policy và diễn tập key recovery. SSE-S3 và SSE-KMS là hai lựa chọn có đánh đổi; KMS cần vòng đời khóa, quyền và backup/recovery riêng, chưa có căn cứ buộc mọi local demo phải dựng KMS.

OWASP ASVS 5.0 V5.4.3 đặt antivirus cho file từ nguồn không tin cậy ở L2. Mục tiêu phù hợp là xác định policy nhận/chia sẻ file, đặt scan gate và fail-closed khi scanner bắt buộc bị lỗi. Hook tùy chọn chưa đủ cho tuyên bố đạt L2. [OWASP ASVS — File Handling](https://raw.githubusercontent.com/OWASP/ASVS/master/5.0/en/0x14-V5-File-Handling.md).

Backup phải khôi phục được metadata, object versions và key material đồng bộ. Versioning hay replication không thay thế một bản backup độc lập khi danh tính ứng dụng có quyền purge object versions. Object Lock/retention cũng có thể làm cleanup/permanent-delete bị từ chối; cần policy giữ/xóa, UX và quota tương ứng trước khi bật. Quy trình PITR cần cả base backup và chuỗi WAL cần thiết. [PostgreSQL 18 — Continuous Archiving/PITR](https://www.postgresql.org/docs/18/continuous-archiving.html).

Đối với presigned URL, cần ghi rõ residual access sau revoke và hành vi download đã bắt đầu. Tài liệu AWS nêu expiry được kiểm tra khi request bắt đầu; stream đang chạy có thể tiếp tục. Đây là semantics AWS để tham khảo, cần xác nhận trên MinIO thực tế và không hứa “TTL hết là mọi kết nối bị cắt”. [AWS S3 — Presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html).

## 7. Thẩm định tài liệu học thuật và so sánh sản phẩm

Đã đối chiếu danh tính/đường dẫn của chín công trình chính qua nhà xuất bản, USENIX, Google Research hoặc trang nghiên cứu của tác giả/trường. Không thấy cơ sở loại chúng như tài liệu bịa. Mức ứng dụng rất khác nhau; kiểm tra danh tính tài liệu không phải tái lập kết quả thực nghiệm của tác giả.

| Tài liệu | Đối chiếu và cách dùng phù hợp |
|---|---|
| [GFS, 2003](https://research.google/pubs/the-google-file-system/) | Hợp lệ; bài học về workload và chịu lỗi, không phải yêu cầu xây file system riêng |
| [Ceph, 2006](https://www.usenix.org/legacy/event/osdi06/tech/weil.html) | Hợp lệ; tham khảo metadata/data và failure handling, không suy rằng BlueDrive cần Ceph |
| [The Tail at Scale, 2013](https://research.google/pubs/the-tail-at-scale/) | Hợp lệ; lý do đo tail latency, không chứng minh ngưỡng p99 của BlueDrive |
| [f4, 2014](https://www.usenix.org/conference/osdi14/technical-sessions/presentation/muralidhar) | Hợp lệ; hot/warm BLOB là hướng sau telemetry, chưa phải backlog bắt buộc |
| [FastCDC, 2016](https://www.usenix.org/conference/atc16/technical-sessions/presentation/xia) | Hợp lệ; CDC/dedup cần threat model, quota và chi phí metadata trước pilot |
| [Cloud-storage traffic efficiency, 2019 — bản tác giả](https://yaoliu-yl.github.io/publications/tompecs-tue.pdf) | DOI 10.1145/3274526 khớp, nghiên cứu tám dịch vụ; không biến kết quả traffic thành dự đoán tăng tốc ứng dụng |
| [Cloud Object Storage Synchronization, 2022 — Stony Brook](https://researchconnect.stonybrook.edu/en/publications/cloud-object-storage-synchronization-design-analysis-and-implemen/) | Khớp tác giả/DOI, có state encoding và push-pull; dùng khi sản phẩm thực sự cần đa thiết bị |
| [Erasure coding survey, 2025 — bản tác giả](https://keyuncheng.github.io/files/publications/tos24ecsurvey.pdf) | Khớp DOI/title/tác giả; không dùng lý thuyết redundancy để chứng nhận single-node local có HA |
| [Chung & Nakamura, JIP 2026 — PDF nhà xuất bản](https://www.jstage.jst.go.jp/article/ipsjjip/34/0/34_86/_pdf/-char/en) | Đã đọc phương pháp và đối chiếu mâu thuẫn 1 GB: abstract nêu 64 MB, nội dung/kết luận nêu 32 MB. Cảnh báo của roadmap là đúng |

Bài JIP dùng Python/SDK/FastAPI, môi trường mạng nhanh và tài nguyên khác browser local. Tham số của nó chỉ là điểm thí nghiệm, chưa đủ lý do đổi concurrency BlueDrive. Phần này cũng không cung cấp bằng chứng ứng dụng hiện tại sẽ tăng 55% hay 400%.

So sánh Seafile CDC khoảng 8 MB là có cơ sở trong tài liệu chính thức. Tuy nhiên, CDC block của Seafile và multipart part 8 MiB của BlueDrive có mục đích khác nhau; trùng con số không tạo ra delta sync/dedup. Seafile còn dùng commit/FS/block objects cho metadata, khác cách đặt namespace trong PostgreSQL hiện tại. [Seafile — Data Model](https://manual.seafile.com/latest/develop/data_model/).

Các nhóm nguồn vendor còn lại trong tài liệu gốc không được thẩm định lại từng đoạn. Đặc biệt, version/capability MinIO, chính sách sản phẩm cạnh tranh, RPO/RTO và SLA vẫn cần xác minh theo môi trường/edition thực tế trước quyết định triển khai.

## 8. Điều chỉnh kế hoạch benchmark

| Đề xuất gốc | Điều chỉnh cần áp dụng |
|---|---|
| App upload 1 GiB/10 GiB | Chưa hợp đồng với `MAX_UPLOAD_SIZE=100 MiB`. Dùng 16 KiB, 1 MiB, 16 MiB, 100 MiB cho app hiện tại; file lớn hơn chỉ là harness storage riêng hoặc scope nâng giới hạn có ADR |
| Part 8/16/32/64/128 MiB | Trước hết đóng hợp đồng part size per-session. Part 128 MiB không cho lợi ích multipart trên file tối đa 100 MiB |
| Parallel 1/4/8/16/32 | Ghi riêng files/tab và parts/file. Hiện app tối đa 3 file × 3 part, tức tối đa khoảng 9 PUT part hoạt động mỗi tab; không gọi 32 part là cấu hình app hiện hành |
| Dataset 100k–1M ngay | Bắt đầu fixture 100/1k/10k trên DB/bucket test riêng; giải quyết query growth và phân trang rồi tăng quy mô theo ngân sách |
| Keyset `(updated_at, id)` | Đặc tả sort theo từng view, folder-first, tie-breaker và loại tài nguyên khi trộn file/folder; thống nhất với sort client hiện tại |
| p95 ≤250 ms/p99 ≤800 ms | Giữ là mục tiêu pilot; ghi cấu hình máy, dataset, vai trò, số SQL, warm/cold cache và concurrency. Chưa được coi là SLO đã đạt |
| 99,9%/1.000+ operation | Có ích cho pilot; sample count và observed failures không tự tạo ra chứng nhận SLA với độ tin cậy thống kê |
| Memory độc lập với file size | Chỉ áp đúng đường native direct GET. Verification có spool/disk; scanner và ZIP còn chi phí đọc file cần đo riêng |

Không nâng concurrency, tăng upload limit, tạo triệu record, restart database hoặc bật fault proxy lên instance đang phục vụ người dùng để hoàn thành một bài benchmark. Cần môi trường test có fixture/cleanup riêng và giới hạn tài nguyên. Các thao tác này chưa được chạy trong lượt thẩm định.

## 9. Roadmap đề nghị sau thẩm định

| Đợt | Việc cụ thể | Gate hoàn thành |
|---|---|---|
| A — Chốt baseline và policy | Lưu source manifest; xác định authorize-at-complete hay authorize-at-publish; định nghĩa file version, quota lịch sử và residual signed URL | Invariant/policy rõ; test tái hiện các quyết định, không có hai nguồn sự thật |
| B — Sửa publication/recovery | D01/D02; kiểm tra stale claim/heartbeat/fencing; retry classification; terminal job convergence | Downgrade/archive/crash không gây publication trái policy hoặc trạng thái job sai; quota đúng một lần |
| C — Data safety và vận hành tối thiểu | Chứng minh TLS/SSE/provider capability; scanner policy; backup DB/object/keys; restore cô lập; metrics backlog/retry/oldest job và CI tối thiểu | Restore đúng manifest/checksum/quyền; scanner outage theo policy; job lỗi có tín hiệu và runbook |
| D — Metadata và giao thức truyền | D03 request-scoped permission/query batching; pagination/sort contract; D04 per-session part size nếu cần tuning | Query growth được kiểm soát; scope/ACL/Back/selection/resume regression vẫn đạt |
| E — Đo và tối ưu có giới hạn | Benchmark app ≤100 MiB, raw storage riêng; network fault fixtures; before/after p50/p95/p99/throughput/RSS/SQL | Kết quả tái lập cùng điều kiện, không làm sai quota/ACL/publication |
| F — Hoàn thiện tính năng người dùng | Resume sau reload, version restore/conflict policy theo nhu cầu; NVDA/VoiceOver, zoom, mobile thật | Hành vi có nghiệm thu thật, UI diễn đạt trung thực giới hạn |
| G — Mở rộng khi có căn cứ | Change feed/desktop sync/CDC/E2EE/HA; SLO và diễn tập vận hành đầy đủ | ADR và lợi ích đo được đủ để gánh thêm độ phức tạp |

C có thể chạy song song một phần với B sau khi đã xác định semantics/retention. Telemetry và backup/restore không nên bị để đến cuối mới bắt đầu. RPO 15 phút/RTO 4 giờ trong tài liệu gốc là đề xuất cần diễn tập chứng minh; không dùng làm cam kết cho local demo.

## 10. Bằng chứng và trạng thái bàn giao

Repository: `C:\Users\dang2\Project\SecureDrive`.

- `frontend/test-results/roadmap-review/roadmap_probes.py`: 6 probe độc lập với application test suite.
- `frontend/test-results/roadmap-review/diagnostic-tests.txt`: **39/39 đạt**, 12,006 giây; không có ca bị bỏ qua trong nhóm chọn lọc.
- `frontend/test-results/roadmap-review/evidence.json`: kết quả định lượng và các tình huống tái hiện.
- `frontend/test-results/roadmap-review/runtime-readonly.json`: metadata runtime đã loại thông tin nhạy cảm.
- `frontend/test-results/roadmap-review/source-manifest.json`: hash của 19 file nguồn trọng yếu.

Giới hạn còn lại: chưa benchmark p95/p99, pentest, diễn tập restore, chạy antivirus thật, xem KMS/provider encryption từ operator, đo client/browser fault hoặc dùng công nghệ hỗ trợ trong lượt này. Không chấm điểm production readiness bằng số lượng test đã pass.

**Bàn giao:** roadmap đã được thẩm định và thu gọn thành thứ tự có gate. Những điểm cần sửa trong source được ghi nhận ở D01–D04, chưa được triển khai trong lượt thẩm định này. Tài liệu gốc được giữ nguyên.

Quy trình source manifest → claim/evidence matrix → probe tái hiện → đối chiếu nguồn sơ cấp → roadmap có gate có thể đóng gói thành Agent Skill thẩm định kiến trúc dùng lại cho dự án.
