# ADR-0003 — Phiên bản kết nối và đích lưu trữ bất biến

> Cập nhật 16/11/2026: [ADR-0010](ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md) chọn SeaweedFS-only. MinIO LAB dưới đây là lịch sử; giữ nguyên quyết định revision bất biến, scope và pinning. Qualification SeaweedFS thật vẫn là gate riêng, không được suy từ test mock hoặc trạng thái DB.

Ngày: 09/11/2026. Trạng thái: đã triển khai S2; gate MinIO LAB thật còn mở.

## Vấn đề

Factory hiện hữu đọc cấu hình storage toàn cục. Nếu chỉ sửa endpoint hoặc binding đang dùng, upload đã bắt đầu, worker hoàn tất, download và cleanup có thể chọn những kho khác nhau. `StorageConfig` đang unique theo tenant/provider nên không thể dùng nó làm lịch sử endpoint một cách an toàn.

Giống chuyển địa chỉ kho hàng: đơn đã gửi phải giữ địa chỉ trên vận đơn; thay địa chỉ mặc định chỉ áp dụng cho đơn mới.

## Quyết định

Giữ `StorageConfig` và thêm `StorageConnectionRevision` chứa endpoint, public endpoint, bucket, region, CA, SSE, network policy và **tên biến môi trường** giữ credential. Không lưu giá trị credential. Đổi endpoint, bucket hoặc tham chiếu credential bằng revision mới. Operator phải giữ credential của revision cũ trong suốt thời gian còn dữ liệu tham chiếu; không ghi đè giá trị của một tên credential đã phát hành để giả làm rotation.

Upload mới, khi cờ multi-cluster routing bật, chụp `storage_config`, `storage_connection`, `endpoint_config_version` một lần. `StorageLocation` giữ cùng revision sau publication. Worker, download, preview, copy và cleanup chọn adapter từ bản ghi đã ghim. Tắt routing không làm dữ liệu đã ghim quay lại factory global. Bản ghi legacy với các cột mới NULL tiếp tục đi qua factory cũ; migration không đoán hoặc backfill đích.

Platform dùng singleton `PlatformStorageBinding`. Personal tenant có thể lấy default này; business tenant phải có binding enterprise của chính mình. Thiếu binding đã kiểm chứng thì upload mới bị từ chối trước khi giữ quota hoặc gọi storage. Một business tenant vẫn chỉ có một cluster active trong MVP; có thể đổi revision trong cluster đó.

## Tin cậy kết nối

Browser chọn ID profile đã được operator duyệt. Browser không cấp URL, CIDR, bucket hay secret. Registry phía server giới hạn profile theo Platform hoặc đúng Organization. Platform Super Admin cấu hình kho Platform; Organization cần explicit `storage.view` và `storage.configure`, không kế thừa từ quyền quản lý nội dung.

Endpoint dùng HTTPS, CA/hostname verification, CIDR rõ ràng, từ chối metadata/link-local và mọi kết quả DNS ngoài policy. Chỉ DEBUG+LAB được dùng HTTP loopback. Client tắt proxy, kiểm tra origin mỗi request và ghim socket vào IP đã duyệt, giữ hostname/SNI gốc cho TLS. DNS được resolve và kiểm tra lại khi tạo client mới; socket của client đó không resolve lại hostname. Public endpoint phải tách khỏi cookie domain ứng dụng.

Transport sử dụng hook connection pool của botocore đã cài. Đây là điểm cần chạy lại kiểm thử socket/TLS khi nâng botocore/urllib3; không coi private API của dependency là contract ổn định vĩnh viễn.

## Read check và LAB proof

HEAD thành công chỉ tạo `read_verified`. Read check có generation và lease hai phút để thử lại sau gián đoạn. Không suy `Healthy`, quorum, upload permission hoặc trạng thái production từ HEAD.

LAB probe cần cờ riêng, profile LAB và xác nhận rõ. Probe tạo bucket mới `bluedrive-scc-<uuid>` cùng object 64 bytes, chỉ thay policy trên bucket tạm đó. Server kiểm tra version, SHA-256 và phản hồi SSE nếu cấu hình; browser đọc trực tiếp từ public endpoint với credentials omit, redirect error và giới hạn 64 bytes. Expected digest không trả về API; browser chỉ gửi digest đã tính.

Chỉ sau browser proof và cleanup thành công mới đánh dấu LAB verified/ready. Dọn dẹp lỗi giữ `cleanup_pending`; có API và command phục hồi. Namespace, ownership receipt và cleanup generation được lưu bền vững. Không xóa object lạ hoặc data bucket; bucket không rỗng sẽ khiến cleanup thất bại. Đây là LAB qualification, không phải chứng nhận production HA/SSE/IAM.

## Trade-off và phạm vi chưa giải quyết

- So với sửa global factory, thêm revision/FK cần migration và giữ credential cũ, đổi lại dữ liệu không đổi kho ngầm.
- So với nhận URL tùy ý, profile registry cần operator cấu hình trước, đổi lại giảm bề mặt SSRF và không đưa secret vào browser.
- Khóa hàng session xuyên RPC khởi tạo multipart giới hạn thời gian là sửa nhỏ cho A02. Transaction/khóa quota có thể chờ theo timeout provider; cần theo dõi nếu lưu lượng lớn. Chưa dùng saga/distributed transaction.
- Counter chặn stale completion cập nhật DB; không thể thu hồi RPC S3 đã gửi. Chưa chứng nhận mọi race orphan/A04 trên MinIO thật.
- Permanent delete vẫn có giới hạn DB/S3 atomicity A03 của audit trước. S2 chỉ sửa chọn đúng adapter, không tuyên bố đã giải quyết A03.

## Rollout và rollback

Áp dụng schema additive trước khi phát hành model đọc cột mới. Giữ mọi cờ OFF; restart đồng bộ web/worker trước khi bật routing trong môi trường đã nghiệm thu. Không tự bật cờ bằng API binding. Worker cũ bị DB guard chặn nếu publication không có location cùng target, nhưng điều đó không thay thế rollout đồng bộ.

Rollback vận hành ưu tiên tắt nhận upload mới/routing và giữ code đọc revision. Khi đã có dữ liệu ghim, không chạy ngược migration hoặc quay về code chỉ biết factory global. Restore backup cần dừng writer và đánh giá dữ liệu phát sinh sau backup; không tự restore trong lượt này.
