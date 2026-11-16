# ADR-0008 — Sao chép Platform và công bố location mới

> **Lịch sử, đã được thay thế về lộ trình ngày 16/11/2026:** [ADR-0010](ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md) bỏ kế hoạch MinIO copy/cutover. `storage_cutover.py`, `audit_storage_cutover`, `migrate_platform_storage` không có trong working tree P0; các mô tả implementation bên dưới là checkpoint ngày cũ, không là hướng dẫn chạy hiện hành. Giữ bài học integrity/revision và bảo vệ dữ liệu runtime; P0 không xóa/sửa dữ liệu.

Ngày: 12/11/2026, Asia/Bangkok. Trạng thái: **đã triển khai công cụ; chưa áp dụng migration/cutover vào dữ liệu thật**. Bằng chứng riêng trong [báo cáo cùng ngày](PLATFORM_CUTOVER_REVIEW_2026-11-12.md).

## Vấn đề

Đổi endpoint toàn cục không chuyển object đã có; location/revision đã ghim không được sửa đích. Legacy session vẫn cần kho gốc cho cleanup. Reset dữ liệu làm mất lịch sử, sharing và đường rollback.

Giống chuyển kho: giữ vận đơn nguồn, kiểm từng kiện rồi lập vận đơn đích mới; đổi quầy giao nhận sau khi kiểm xong.

## Quyết định

Tái sử dụng adapter S3 và `StorageLocation`; không thêm provider, schema hoặc worker. `migrate_platform_storage` nhận manifest private có digest, exact source IDs, snapshot metadata và revision S3 Platform ready. Phạm vi là personal Tenant và Personal Workspace, không chuyển Enterprise vào Platform. Nguồn bao gồm cả config nhãn `s3` chưa ghim tại MinIO cũ, vì nhãn provider không chứng minh endpoint thực tế.

`plan` chỉ đọc DB. `copy` đọc version nguồn, spool bytes ra file tạm, tính SHA-256 toàn file, giữ user metadata, ghi key `primary/<uuid5>` xác định theo manifest/source và đọc lại bytes/metadata/version. Biên nhận lưu atomically từng object. Retry kiểm key có sẵn thay vì PUT lặp. Version ID của hai provider lưu riêng. Ciphertext giữ nguyên bytes; source encrypted chưa ghim version hoặc checksum metadata không rõ bị chặn để phân loại, không tự đổi format/key.

Bổ sung 13/11/2026: source plaintext legacy thiếu header VersionId hoặc có `null` được ghi receipt `source_version="null"`. Đây là kiểm chứng nội dung bằng size/full SHA-256 từ FileVersion trong cửa sổ dừng writer, không phải version bất biến. Không truyền pin giả vào adapter hoặc nới kiểm version thật. Copy/publish/rollback đọc lại toàn bộ bytes; rollback còn so với hash DB, không chỉ receipt. Target vẫn bắt buộc VersionId thật. Source config phải active/read_only; ciphertext chưa có pin thật tiếp tục BLOCKED.

Lập kế hoạch có tùy chọn `--allow-unverified-target` để operator review exact mapping khi revision đã read-check nhưng chưa đủ gate. Đây chỉ là xuất file dự kiến, được đánh dấu `qualification_at_plan`; mặc định vẫn đòi ready. Copy/publish không nhận tùy chọn này và luôn kiểm gate hiện tại. Trade-off là có manifest để review sớm nhưng chưa thể thực thi; không dùng báo cáo plan làm chứng nhận provider hoặc gán trạng thái ready bằng SQL.

`publish` kiểm lại cả lô rồi thêm location S3 trong một transaction, giữ location nguồn và FileVersion. Reader hiện có chọn primary available mới nhất; công cụ kiểm selector cuối cùng và từ chối location cạnh tranh. Không sửa trigger bất biến. `rollback` kiểm nguồn rồi chuyển location đích về pending, không xóa object và không yêu cầu target đang hoạt động. Với source legacy chưa ghim, latest version phải vẫn khớp biên nhận để đường đọc cũ đúng dữ liệu.

Lệnh ghi cần approval JSON khớp digest/hành động, operator/reason, xác nhận dừng writer và hash bốn evidence: restore DB cách ly, backup nguồn, bảo toàn key/config legacy và gate storage. Hash xác minh file operator đã duyệt không đổi; công cụ không tự chứng nhận nội dung báo cáo. Khóa manifest ngăn chạy đồng thời cùng file. Publication khóa bảng file/upload, timeout 5 giây và kiểm không còn upload/job/reservation hoạt động. Operator phải giữ cửa sổ bảo trì vì transaction PostgreSQL không khóa writer S3 bên ngoài.

## Phương án loại bỏ

- Sửa global endpoint hoặc update location/revision: đổi kho ngầm, vi phạm bất biến và có thể xóa nhầm kho.
- Reset rồi tạo lại file: mất dữ liệu/tham chiếu.
- Thêm adapter SeaweedFS/journal model: trùng contract và dữ liệu đã biểu diễn được bằng manifest/location.
- Xóa nguồn sau copy: mất rollback trước khi nghiệm thu app/browser/worker.

## Hệ quả, rollout và rollback

Công cụ không đổi binding, endpoint, feature flag, credential hoặc dừng MinIO. Operator dùng connection/binding hiện có sau approval. Giữ global/credential nguồn khi còn legacy session/location. File tạm cần đủ dung lượng cho object lớn nhất; single PUT tuân thủ giới hạn provider.

`infrastructure.0006_allow_deleted_upload_history` sửa tương thích lifecycle permanent-delete: location/version đã xóa hết mới được tháo FK session thành công, target vẫn bất biến, không cho retarget hay INSERT publication rỗng. Giữ consumed history và cho cleanup sau xóa. Operator phải áp dụng migration trước code mới ở môi trường phục vụ; phiên này chỉ chạy trên DB test. Không reverse sau khi đã có successful history tháo FK vì trigger cũ chặn cập nhật lịch sử; dùng forward-fix.

Backup DB kèm object versions và key/config private; restore thử vào DB riêng, không restore đè. Rollback location chỉ hoàn nguyên lô cũ, không di chuyển ngược file mới trên SeaweedFS. Sau khi có dữ liệu mới, giữ code reader revision và SeaweedFS để đọc chúng. Chỉ ngừng MinIO khi mọi tham chiếu đọc/cleanup còn lại đã xử lý theo manifest riêng và có bằng chứng runtime.

## Nguồn

- [ADR-0003](ADR-0003-immutable-storage-connections.md), [runbook Platform](../infra/seaweedfs/README.md).
- [PostgreSQL pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html), [pg_restore vào DB mới](https://www.postgresql.org/docs/18/app-pgrestore.html).
- [Boto3 GetObject/VersionId](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/get_object.html), [PutObject/metadata](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_object.html).
