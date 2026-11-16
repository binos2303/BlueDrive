# ADR-0009 — Qualification runtime tách provisioning bucket

> Cập nhật 16/11/2026: [ADR-0010](ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md) thay lộ trình cutover/decommission MinIO bằng SeaweedFS-only. Các quyết định qualification/identity/browser proof/cleanup vẫn dùng; trạng thái và bằng chứng 13/11 bên dưới là lịch sử, không chứng nhận runtime hôm nay.

Ngày: **13/11/2026**, Asia/Bangkok. Trạng thái: **đang triển khai/kiểm chứng**; kết quả runtime và schema phục vụ được ghi riêng tại [báo cáo qualification](PLATFORM_QUALIFICATION_2026-11-13.md).

## Vấn đề

Probe LAB hiện có yêu cầu cùng identity tạo/tag/version/CORS/xóa bucket tạm. Identity ứng dụng Platform đã giới hạn đúng bucket được duyệt nên bị từ chối CreateBucket, dù HEAD/versioning/CORS ở data bucket đạt. Tăng quyền runtime để vượt probe sẽ làm kết quả kiểm định lệch với quyền cần dùng hàng ngày.

Giống kho hàng: operator chuẩn bị kho và cấp thẻ; nhân viên dùng đúng thẻ đó để kiểm nhập/xuất trong kho đã được giao.

## Quyết định

Giữ flow provisioning LAB và thêm mode qualification runtime vào service/probe hiện có. Mode được lưu và bất biến theo probe; mặc định LAB để giữ lịch sử. Runtime dùng bucket của revision, namespace fixture do server sinh và receipt exact version/upload; không thêm adapter, worker hoặc dependency.

Qualification runtime dùng cùng identity ứng dụng của connection revision cho PUT/GET/HEAD/DELETE, multipart, presigned PUT/GET, metadata, immutable version, SHA-256 toàn bytes, browser CORS và cross-bucket denial. Không sửa CORS/versioning/policy bucket đang dùng hoặc yêu cầu CreateBucket/PutBucketPolicy. Deny thao tác data-plane bắt buộc làm qualification thất bại; deny thao tác provisioning không cần thiết không được dùng để kết luận runtime không đạt.

Browser upload challenge dùng UploadPart của multipart riêng; sau completion/abort, URL cũ không thể tạo thêm object fixture bằng ordinary PUT. Browser đọc GET đã ghim version, gửi digest/receipt; server đối chiếu dữ liệu/part thật và cleanup. URL ký/credential không lưu trong probe checks hoặc báo cáo công khai.

READY phụ thuộc toàn bộ check bắt buộc của mode, browser proof, expiry/generation hiện tại và cleanup thành công. Pending/failed cleanup không được thành công giả. Retry giữ receipt và lịch sử; khóa probe/generation ngăn kết quả stale thay trạng thái mới. Schema ràng buộc runtime bucket bằng bucket revision và giữ namespace/key/mode bất biến, trong khi nhiều probe runtime lịch sử có thể dùng cùng bucket.

Probe LAB cũ `bucket_created=false` cần proof vắng mặt thật để reconcile. Service kiểm quyền cấu hình, lý do, actor audit và HEAD 404 bằng operator identity hiện hữu; không coi 403 là vắng mặt. Reconciliation đóng lịch sử failed/expired, không cấp READY hoặc thay credential/revision. Qualification mới vẫn phải chạy đầy đủ bằng identity ứng dụng.

## Phương án loại bỏ

- Cấp quyền quản trị bucket cho runtime: tăng quyền không cần thiết và thay điều kiện đang cần kiểm chứng.
- Dùng operator identity để qualification data-plane: che được lỗi IAM của identity ứng dụng.
- Chỉ dùng HEAD/read check hoặc gán READY trực tiếp: thiếu bằng chứng ghi, browser, integrity và cleanup.
- Chuyển probe LAB sang data bucket mà không lưu mode/ownership: cleanup cũ có thể gọi bucket-level deletion trên đích không thuộc fixture.
- Thêm adapter/service song song riêng SeaweedFS: lặp trách nhiệm của S3 adapter và connection service hiện có.

## Hệ quả, rollout và rollback

Runtime qualification có cờ riêng mặc định OFF. Bật trong process/môi trường đã được duyệt, sau schema tương thích; không bật routing hoặc đổi binding cùng lúc. Migration probe mới phụ thuộc `infrastructure.0006_allow_deleted_upload_history`, nên quyết định áp dụng vào DB phục vụ phải bao gồm cả ảnh hưởng trigger của 0006, backup và restore rehearsal. Không đồng nhất test DB đã migrate với serving DB đã migrate.

Trước rollback schema, phải kiểm probe runtime còn pending hoặc lịch sử dùng bucket lặp; không tự reverse khi dữ liệu mới không còn thỏa schema cũ. Giữ forward-fix làm lựa chọn khi lịch sử đã phát sinh. Tắt cờ chặn qualification mới không thay target của upload/location đã ghim và không thay trách nhiệm cleanup fixture đã có.

READY tại local HTTP/LAB chỉ chứng minh năng lực data-plane đã kiểm tra. Production TLS/SSE/HA, migration data, freeze, backup hiện hành, publication/routing và decommission MinIO vẫn có gate/approval riêng theo ADR-0008. Qualification không tạo FileVersion hoặc công bố StorageLocation của dữ liệu nguồn.

## Nguồn

- [ADR-0003 — revision bất biến](ADR-0003-immutable-storage-connections.md), [ADR-0008 — copy/publication](ADR-0008-platform-storage-copy-and-publication.md).
- [Connection service](../backend/infrastructure/connections.py), [probe service](../backend/infrastructure/connection_probes.py), [profile/transport guard](../backend/infrastructure/connection_profiles.py).
- [Runbook Platform](../infra/seaweedfs/README.md), [S2 runbook](STORAGE_CONTROL_CENTER_S2_RUNBOOK.md), [checkpoint trước sửa](PLATFORM_CUTOVER_CHECKPOINT_2026-11-13.md).
