# Storage Control Center S4 — operator runbook

Ngày: 09/11/2026. Triển khai code không tự bật collector hoặc thay đổi MinIO. Đọc ADR-0005, G2 và roadmap07 trước vận hành.

## 1. Điều kiện trước bật

1. Chốt MinIO edition/version/license, cluster UUID và node UUID đúng inventory. Hoàn tất G2 với danh tính read-only, CA và mạng đã duyệt. Không dùng root credential.
2. Prometheus/TSDB có exporter đúng version; truy vấn readiness phải dựa trên bằng chứng read/write quorum, không suy từ process liveness. Host và MinIO up là hai bằng chứng riêng.
3. Duyệt từng expression và timestamp_expr bằng raw samples. Aggregation phải giữ expected_labels và node UUID. Không aggregate lẫn tenant; không đưa bucket/object/token/URL khách hàng vào output. Kiểm tra nguồn ngắt thực thì timestamp thực sự ngừng tiến.
4. Bảo vệ biến môi trường token, profile và CA phía server; duyệt retention TSDB và incident. Nền tảng hiện không cài ASGI server: chọn/duyệt ASGI deployment trước dùng SSE; WSGI vẫn dùng polling.

## 2. Schema và cấu hình

Áp dụng additive migration `infrastructure.0005_telemetry_snapshots_and_alerts` sau backup DB và kiểm tra kế hoạch migration. Hai bảng mới không sửa file/quota/binding hiện có. Web và collector phải cùng source version.

`SECUREDRIVE_STORAGE_MONITORING_ENABLED=false` mặc định. `SECUREDRIVE_STORAGE_MONITORING_PROFILES={}` mặc định. Không chỉnh actual .env để chạy acceptance fixture.

Profile dưới đây là mẫu **chưa duyệt và không chạy được**. Thay ID, version, expressions theo bằng chứng thật; không chỉ đổi approved thành true:

```json
{
  "reviewed-cluster": {
    "scope": "organization",
    "tenant_id": "REPLACE_TENANT_UUID",
    "cluster_id": "REPLACE_CLUSTER_UUID",
    "revision": 1,
    "approved": false,
    "review_ref": "REPLACE_APPROVAL_REFERENCE",
    "edition": "community",
    "provider_version": "REPLACE_EXACT_INVENTORY_VERSION",
    "metrics_schema": "minio_v2",
    "endpoint_url": "https://metrics.example.invalid",
    "allowed_networks": ["10.31.0.0/24"],
    "token_env": "BLUEDRIVE_REVIEWED_PROMETHEUS_TOKEN",
    "ca_bundle": "REPLACE_SERVER_CA_PATH",
    "lab": false,
    "stale_after_seconds": 90,
    "capacity_thresholds": {"warning": 80, "critical": 95},
    "expected_labels": {"bluedrive_cluster_id": "REPLACE_CLUSTER_UUID"},
    "queries": {
      "cluster_read_ready": {"expr": "REVIEW_READ_QUORUM", "timestamp_expr": "REVIEW_READ_SOURCE_TIMESTAMP"},
      "cluster_write_ready": {"expr": "REVIEW_WRITE_QUORUM", "timestamp_expr": "REVIEW_WRITE_SOURCE_TIMESTAMP"},
      "cluster_failed_disks": {"expr": "REVIEW_FAILED_DISKS", "timestamp_expr": "REVIEW_DISK_SOURCE_TIMESTAMP"},
      "cluster_offline_nodes": {"expr": "REVIEW_OFFLINE_NODES", "timestamp_expr": "REVIEW_NODE_SOURCE_TIMESTAMP"}
    }
  }
}
```

Platform profile: scope=platform, tenant_id=null. AIStor profile dùng aistor_v3 và edition aistor/enterprise tương ứng inventory; không tự chuyển schema. Có đúng một profile/cluster, tối đa100 profile. Sửa bất kỳ nội dung profile cần tăng revision. Tăng revision không xóa mẫu cũ; UI Unknown cho tới có lần thu thập mới hợp lệ.

Tám metric cluster cho phép: cluster_read_ready, cluster_write_ready, cluster_failed_disks, cluster_offline_nodes, raw_capacity_bytes, usable_capacity_bytes, usable_free_bytes, logical_used_bytes. Bốn metric đầu bắt buộc; readiness là0/1, counts là số nguyên không âm.

Tám metric node tùy chọn: node_cpu_percent, node_ram_percent, node_uptime_seconds, node_filesystem_free_bytes, node_network_rx_bytes_per_second, node_network_tx_bytes_per_second, node_minio_up, node_host_up. Mỗi vector node phải có bluedrive_node_id trùng UUID thuộc cluster. Thiếu một số đo hiển thị Not reported; thiếu up proof không được Healthy. CPU/RAM dùng0–100; network bytes/s, uptime seconds, dung lượng bytes.

## 3. Thu thập và phục hồi

Chỉ sau khi các gate trên đạt, cấu hình server-side rồi chạy một lượt:

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py collect_storage_telemetry
```

Collector không được khởi động tự động bởi web/app. `--watch --interval 30` dành cho process supervisor đã duyệt; interval15–60s, nghỉ sau mỗi sweep. Tối đa4 query concurrent/profile; mỗi metric cần query giá trị và timestamp. Tổng lượt có deadline25s và có thể chờ request đang chạy kết thúc theo deadline/socket timeout. Không phải SLA scrape30s khi toàn nguồn đang lỗi. DNS của hệ điều hành và TLS/CA thực vẫn cần vận hành/đo trên host đích.

Lệnh trả lỗi khi không có profile hợp lệ, cluster không tồn tại hoặc có lượt thu thập lỗi; không in token, expression hay raw error. Không thay readiness/DB bằng số fixture để nghiệm thu. Mỗi sweep kiểm tra stale và dedupe incident. Nếu collector dừng, GET/browser vẫn đánh dấu stale theo TTL; incident telemetry_stale được tạo khi collector sweep hoạt động trở lại, không có watchdog độc lập được triển khai ở giai đoạn này.

## 4. Nghiệm thu G4 thật

- Đối chiếu DTO với raw samples và timestamp của đúng cluster/node. Kiểm tra raw/usable/free/logical không lẫn nhau.
- Ngắt exporter/collector trong LAB và quan sát Unknown/stale đúng hạn; không gán lỗi vào production. Khôi phục, đối chiếu incident resolve và lần thành công cuối.
- Tạo lỗi quorum trong LAB được chủ sở hữu duyệt; xác nhận Critical và hai nguồn node, không chỉ sửa JSON dashboard.
- Đăng nhập hai tenant và Platform riêng, kiểm tra403/404, revoke grant/session/password trong stream, ACK có CSRF/audit và conflict.
- Đo SSE qua ASGI + reverse proxy (buffering off, heartbeat5s, lifetime~60s), reconnect/cursor và load nhiều client. Không dùng Django runserver WSGI làm bằng chứng SSE vận hành.
- Kéo bố cục chưa lưu rồi cập nhật telemetry: vị trí/filter/selection giữ nguyên; kiểm tra desktop/mobile/dark, focus và viewport thực.

## 5. Rollback

Tắt monitoring flag, dừng process collector do operator quản lý; UI quay về inventory. Giữ hai bảng mới để lưu incident/audit; không cần reverse migration hoặc xóa dữ liệu. Không rollback S2/S3, binding, quota hay object storage. Quay về profile cũ bằng một revision mới được duyệt, không giảm revision. .env và secrets không xuất vào báo cáo.
