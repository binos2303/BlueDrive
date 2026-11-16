# ADR-0010 — Kiến trúc đích SeaweedFS, Enterprise My Drive và mã hóa phía client

Ngày: **16/11/2026**, Asia/Bangkok. Trạng thái: **kiến trúc đích đã được người dùng thống nhất; P0 chỉ đồng bộ tài liệu và baseline**. Không phải xác nhận đã triển khai hoặc đã nghiệm thu runtime. Bằng chứng và backlog tập trung tại [P0 baseline](REFACTOR_P0_BASELINE_2026-11-16.md).

## Vấn đề

Hướng dẫn đang trộn ba thời điểm: AES phía server và MinIO trước đây, implementation S3/revision/finalizer hiện có, và kiến trúc Enterprise/CSE sắp triển khai. Người tiếp tục có thể sửa sai default tenant, chạy công cụ cutover không còn trong working tree, hoặc hiểu nhầm multipart đã mã hóa ở browser.

Giống bản thiết kế kho hàng và sổ vận hành: đổi bản thiết kế không tự chuyển hàng, đổi chủ hàng hoặc cấp chìa khóa mới cho nhân viên.

## Quyết định đã thống nhất

- Giữ Next.js/React/TypeScript/Tailwind; Django REST Framework là control plane; PostgreSQL ứng dụng giữ identity, quyền, quota, metadata, routing và audit.
- Object storage đích **chỉ SeaweedFS qua S3-compatible API**. Giữ adapter S3 chung, không tạo adapter/provider riêng chỉ để đổi nhãn sản phẩm. Giá trị `s3` trong DB không chứng minh endpoint thực tế là SeaweedFS.
- Platform và Enterprise có storage độc lập. Filer dùng PostgreSQL metadata riêng; DB này không thay DB nghiệp vụ Django. Enterprise dùng cùng application codebase, Tenant business và Storage Binding riêng; không thêm một Organization model song song.
- Enterprise My Drive thuộc Organization. Không mặc định đưa nhân viên về Platform Personal Tenant. Cách chọn Organization khi có nhiều membership, cấp tài khoản và biểu diễn vùng My Drive riêng từng nhân viên cần contract chi tiết trước implementation.
- Upload/download đi trực tiếp giữa browser và SeaweedFS sau khi Django kiểm quyền, chọn đúng storage và cấp URL ngắn hạn. Django vẫn quản lý quota, metadata và finalization. Các ngoại lệ hiện có như reader AES legacy, preview và ZIP phải được phân loại trước khi thay thế.
- **Client-side encryption là thiết kế đích**: AES-256-GCM kết hợp public/private key và organization key recovery. Khóa phải có nguồn ngẫu nhiên mật mã; không suy private key từ username/email/thông tin cá nhân có thể đoán. P0 không chọn thuật toán bất đối xứng, format ciphertext/chunk, key custody hoặc cơ chế khôi phục cụ thể.
- MinIO bị loại khỏi kiến trúc đích. Không thực hiện cutover, không lập yêu cầu sao chép/bảo toàn dữ liệu thử nghiệm MinIO cũ để đạt kiến trúc mới. Quyết định này **không cấp quyền xóa hoặc sửa dữ liệu runtime hiện tại**, dừng dịch vụ hay thay endpoint/credential/key.

## Quan hệ với ADR trước

| ADR | Phần còn hiệu lực | Phần được ADR-0010 thay thế hoặc giới hạn |
| --- | --- | --- |
| [0001](ADR-0001-saas-file-transfer-and-encryption.md) | Django cấp quyền; staging/finalization; quota và integrity | MinIO làm đích; download mặc định qua Django; hoãn CSE và AES server làm đích mã hóa. Reader legacy vẫn phải hoạt động cho dữ liệu hiện có. |
| [0002](ADR-0002-storage-inventory-ownership.md) | Platform/Enterprise ownership, capability độc lập, Tenant business | Mô tả S1 là lịch sử triển khai, không phải trạng thái đủ của toàn ứng dụng hôm nay. |
| [0003](ADR-0003-immutable-storage-connections.md) | Revision bất biến, pinning, scope, profile và SSRF guards | MinIO LAB không còn là gate provider tương lai; dùng SeaweedFS. Compatibility của dữ liệu/revision đang tồn tại vẫn được giữ. |
| [0007](ADR-0007-platform-filer-postgres-container.md) | Filer PostgreSQL riêng và cách ly Platform/Enterprise | Trạng thái chưa cutover chỉ là checkpoint lịch sử, không là mục tiêu của P1–P8. |
| [0008](ADR-0008-platform-storage-copy-and-publication.md) | Bài học về revision bất biến, DB/object-store không atomic và không retarget dữ liệu | Kế hoạch copy/publication/rollback MinIO → SeaweedFS không còn là lộ trình được yêu cầu. Công cụ được mô tả không có trong working tree P0; không dùng ADR như chứng cứ executable tồn tại. |
| [0009](ADR-0009-runtime-storage-qualification.md) | Tách identity provisioning/runtime, checksum/version/browser proof/cleanup | Qualification không cấp quyền cutover hoặc chứng nhận production; phần decommission MinIO là lịch sử. |

Không xóa lịch sử ADR hoặc sửa lại bằng chứng có ngày để giống kết quả hôm nay.

## Phương án so sánh và hệ quả

| Phương án | Lợi ích | Đánh đổi / kết luận |
| --- | --- | --- |
| Tiếp tục hỗ trợ đa provider và cutover MinIO | Giữ lộ trình cũ | Không đúng phạm vi mới; loại khỏi đích, không thực thi cleanup trong P0. |
| Adapter riêng SeaweedFS | Nhãn sản phẩm rõ | Lặp contract S3 và callers; giữ adapter hiện có, chứng minh năng lực provider bằng gate thật. |
| Enterprise application riêng | Có thể tách chu kỳ triển khai | Nhân đôi auth/quota/UI; giữ codebase chung và kiểm cách ly Tenant/Binding. |
| Giữ Personal Tenant làm default cho mọi nhân viên | Ít thay đổi code | Trái Enterprise My Drive đã thống nhất; cần đổi contract default/provisioning có regression. |
| AES phía server làm đích | Tái dùng scanner/preview/ZIP | Không đạt CSE; chỉ giữ compatibility cho legacy, không tự tái mã hóa dữ liệu. |
| CSE và recovery theo Organization | Đạt yêu cầu về vị trí mã hóa và khôi phục doanh nghiệp | Thay đổi upload/download, sharing, kiểm nội dung và quản lý khóa; cần thiết kế/review riêng. Không tuyên bố zero-knowledge chỉ vì có CSE. |

Với CSE, server có thể kiểm bytes ciphertext đã nhận nhưng không tự kiểm nội dung plaintext nếu không được giao quyền giải mã. Vì vậy semantics của SHA-256, kích thước tính quota, MIME, scanner, preview, ZIP, chia sẻ và recovery phải được duyệt cùng format mã hóa trước P6. Không dùng checksum ciphertext để tuyên bố plaintext an toàn. Giống kiểm niêm phong kiện hàng: chứng minh kiện không đổi chưa chứng minh thứ bên trong đúng yêu cầu.

## Gate trước implementation và vận hành

1. Chốt contract Organization context/My Drive, provisioning, offboarding, quyền phê duyệt và recovery; các mục chưa có quy tắc cụ thể được ghi trong backlog P0.
2. Thiết kế CSE có threat model, nonce/chunk/AAD, envelope/key versions, đổi thiết bị, mất khóa, recovery có audit và compatibility; review độc lập trước đổi crypto/API/schema.
3. Chạy regression PostgreSQL riêng và gate SeaweedFS/browser/finalizer trên fixture có phạm vi. PASS unit hoặc một revision `ready` trong DB không thay nghiệm thu provider hiện tại.
4. Mọi thay runtime/migration/flag/endpoint và cleanup dữ liệu cần đúng phạm vi phê duyệt riêng. P0 không thực hiện các bước đó; không commit/push/deploy.

P0 rollback chỉ hoàn nguyên phần tài liệu của P0 sau review; không có DB/object/key nào được thay để rollback. Giai đoạn sau phải mô tả rollback hoặc forward-fix theo schema và dữ liệu thực tế trước khi được triển khai.

## Nguồn

- Quyết định kiến trúc và ranh giới P0: yêu cầu người dùng ngày 16/11/2026; được chuyển thành quyết định ở tài liệu này, không lưu hội thoại hoặc attachment private trong repo.
- Bằng chứng implementation: [P0 inventory, findings và gates](REFACTOR_P0_BASELINE_2026-11-16.md); các file source được dẫn trong đó.
- [W3C Web Cryptography Recommendation 2017](https://www.w3.org/TR/2017/REC-WebCryptoAPI-20170126/): API mã hóa và tạo/quản lý khóa; không tự cung cấp quy trình recovery doanh nghiệp.
- [Django 5.2 on_delete](https://docs.djangoproject.com/en/5.2/ref/models/fields/#django.db.models.ForeignKey.on_delete): đối chiếu lifecycle owner/audit.
- [DRF SessionAuthentication](https://www.django-rest-framework.org/api-guide/authentication/#sessionauthentication): session và CSRF vẫn cần cho control plane.
- [S3 checksum semantics](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html): full-object/composite checksum khác nhau; tài liệu AWS không chứng nhận SeaweedFS tương thích.
