# S2 — Chuẩn bị và nghiệm thu Connect Existing

> Cập nhật P0 16/11/2026: [ADR-0010](ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md) chọn SeaweedFS-only. Các tham chiếu MinIO/cutover và trạng thái 09–13/11 bên dưới là lịch sử; không là yêu cầu tiếp tục lộ trình cũ. Giữ contract profile/revision/capability và phân biệt LAB với runtime qualification; xem [P0 gaps/gates](REFACTOR_P0_BASELINE_2026-11-16.md) trước vận hành, không bật flag hoặc chạy probe ghi live trong P0.

Ngày: 09/11/2026. Runbook cho operator; ví dụ bên dưới là placeholder, không phải cấu hình đã nghiệm thu.

Cập nhật qualification Platform 13/11/2026: xem [báo cáo qualification runtime](PLATFORM_QUALIFICATION_2026-11-13.md) và [runbook Platform](../infra/seaweedfs/README.md). Quy trình tạo bucket LAB bên dưới vẫn là kiểm tra provisioning riêng; không cấp thêm quyền quản trị bucket cho identity runtime để vượt bài LAB.

## Trạng thái hiện tại

Code/UI và schema local đã triển khai. Cả năm cờ storage mặc định OFF, registry mặc định `{}`. Không có migration backfill binding. Chưa chạy probe lên MinIO thật trong S2; không bật routing chỉ vì unit/browser fixture đạt.

## Chuẩn bị môi trường LAB

1. Chốt edition/version/license, endpoint TLS/CA, public endpoint tách cookie, bucket thử và CIDR thực của môi trường LAB. Không dùng dữ liệu production hoặc MinIO root identity.
2. Cấp identity riêng đúng scope. Data-plane identity cần thao tác upload, reconcile, đọc version, publication và cleanup theo policy đã review. Probe provisioning LAB dùng **cùng profile** và cần quyền tạo/tag/version/CORS/xóa bucket tạm `bluedrive-scc-*`; chỉ dùng khi phạm vi LAB đã duyệt các quyền này. Qualification runtime kiểm fixture trong bucket đã được duyệt, bằng identity ứng dụng hiện có; không yêu cầu CreateBucket/PutBucketPolicy hoặc sửa CORS/versioning. Không mặc định thêm quyền LAB vào profile runtime.
3. Operator cung cấp secret bằng biến môi trường có tên phiên bản. Duy trì tên cũ khi còn UploadSession/StorageLocation tham chiếu. Không paste secret vào UI, log hoặc báo cáo.
4. Khai báo registry JSON server-side, ví dụ:

```json
{
  "org-a-v1": {
    "scope": "organization",
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "label": "Organization A LAB",
    "provider": "minio",
    "edition": "operator-approved-edition",
    "provider_version": "operator-approved-version",
    "endpoint_url": "https://minio.lab.example.invalid",
    "public_endpoint_url": "https://objects.lab.example.invalid",
    "bucket": "org-a-lab-data",
    "region": "us-east-1",
    "allowed_networks": ["10.30.0.10/32"],
    "access_key_env": "ORG_A_LAB_ACCESS_V1",
    "secret_key_env": "ORG_A_LAB_SECRET_V1",
    "lab": true,
    "server_side_encryption": "AES256"
  }
}
```

Đặt JSON thành giá trị `SECUREDRIVE_STORAGE_CONNECTION_PROFILES`. Profile Platform dùng `scope: "platform"`, bỏ tenant_id; không sao chép profile Organization sang Platform để vượt tenant boundary. CA riêng đặt bằng `ca_bundle` đã được operator kiểm tra. Không thêm trường raw secret vào JSON.

5. Schema: `python manage.py migrate`. Cần backup và kiểm tra DB đích trước khi chạy trên môi trường khác. Local hiện đã áp dụng infrastructure0001–0004 và files0017 sau backup; không cần rollback/reapply để mở UI.
6. Restart đồng bộ web và tất cả finalizer workers, trong cửa sổ triển khai phù hợp. Không có tiến trình hiện hữu nào bị agent tự dừng/restart trong S2.

## Kiểm tra theo thứ tự

1. Chỉ bật `SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED`. Platform Super Admin mở `/admin/infrastructure/topology`; Organization có grant mở `/organization/storage`. Menu ẩn khi capability không khả dụng. Org Owner cấp quyền bằng access API S1; không mặc định cấp quyền storage cho mọi Org Admin.
2. Register approved profile với lý do. Chạy read check: thử chứng chỉ đúng/sai, credential bị từ chối, timeout, DNS ngoài CIDR, public CORS thiếu và versioning thiếu. Không thay policy data bucket từ UI.
3. Chọn đúng mode theo mục tiêu: provisioning LAB cần `SECUREDRIVE_STORAGE_LAB_PROBES_ENABLED` và xác nhận tạo bucket tạm; qualification runtime theo [runbook Platform](../infra/seaweedfs/README.md) dùng bucket/revision hiện hữu và xác nhận fixture riêng. Browser phải PUT/GET/hash theo contract của mode; server phải dọn đúng receipt. Không coi read check, operator smoke hoặc state tự gán là qualification runtime.
4. Cố ý chặn browser GET hoặc DeleteBucket: không được bind sớm. Reload phải tìm lại pending sample; retry browser/cleanup phải tiếp tục được. Không xóa tay data bucket khi cleanup lỗi.
5. Chọn Prepare for new uploads; generation cũ phải trả conflict khi định đổi sang đích khác. Binding chỉ chuẩn bị metadata; cờ routing không đổi.
6. Sau khi toàn bộ web/worker cùng version và LAB đạt, mới thử bật `SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED` trong LAB. Upload A, đổi revision B, hoàn tất/download/copy/hủy/cleanup A; A phải giữ kho cũ, upload mới phải dùng B. Kiểm tra quota workspace/private và verify byte/version trên MinIO thật.
7. Lưu evidence đã loại credential/presigned URL, xác nhận gate G2 trước S3. Không triển khai node/pool/agent thật theo gate này.

## Phục hồi mẫu thử

API cleanup chỉ thao tác fixture có receipt và namespace hợp lệ. `cleanup_storage_probes --limit 100` xử lý cleanup_pending và probe hết hạn. `run_upload_finalizer` mới gọi cleanup upload/probe mỗi 60 giây; worker đã chạy từ trước phải restart mới nhận code đó. Giữ quyền/credential cleanup của revision cũ cho đến khi dọn xong. Nếu ownership không được chứng minh hoặc có object lạ, command giữ pending để operator điều tra; không quét/xóa tùy ý.

Probe provisioning thất bại trước CreateBucket vẫn có thể pending vì identity ứng dụng không được HEAD bucket tạm. `bucket_created=false` riêng lẻ hoặc HEAD 403 chưa chứng minh bucket không tồn tại. Dùng service reconciliation có quyền cấu hình, lý do/audit và proof HEAD 404 bằng identity operator hiện hữu; đóng lịch sử failed/expired, không làm revision READY. Không update SQL, đổi credential revision hoặc xóa lịch sử để mở retry.

## Tiêu chí đóng G2 còn lại

Một cluster LAB thật với edition/license được duyệt; TLS/IAM/CORS/version/SSE phù hợp; browser GET thật không mang cookie; đổi binding giữa upload và worker thật; fail/retry/cleanup thật; restart/rollback drill. Các kiểm thử mocked S3 và TLS server tạm trong repository không thay thế các bằng chứng này.
