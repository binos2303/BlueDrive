# ADR-0005 — Storage monitoring: source freshness, scoped snapshots and SSE

Ngày: 09/11/2026. Trạng thái: code triển khai sau cờ OFF; chưa qua G2/G4 runtime.

## Vấn đề và lựa chọn

Inventory và kết nối S3 thành công không chứng minh node đang khỏe. Poll từng node từ trình duyệt làm số request tăng theo kích thước bản đồ; proxy trực tiếp Prometheus ra browser dễ lộ truy vấn và credential. Ghi mỗi mẫu vào PostgreSQL ứng dụng cũng tạo thêm một hệ time-series phải vận hành.

Chọn adapter Prometheus chỉ đọc, profile do operator duyệt theo cluster/edition/version. PostgreSQL giữ một snapshot hiện tại và incident alerts; lịch sử metric nằm ở TSDB. Browser đọc snapshot theo quyền storage.view + storage.monitor; SSE chỉ phát yêu cầu resync, cùng snapshot phục vụ polling khi chạy WSGI. Giống bảng điều khiển kho: cảm biến gửi số đo về trung tâm, người xem nhận bảng tổng hợp theo kho được phân quyền.

Không tự đoán tên metric giữa Community v2 và AIStor v3. Profile chứa expression giá trị và expression timestamp nguồn riêng, nhãn cluster/node, TTL và ngưỡng capacity. Cần review expression và đối chiếu nguồn thật trước bật cờ. `timestamp(aggregate_expression)` có thể cho thời điểm đánh giá mới dù mẫu gốc cũ: không dùng nó làm bằng chứng freshness. Expression timestamp phải lấy timestamp mẫu gốc trước khi aggregate và giữ nhãn scope.

## Bảo đảm triển khai

- HTTPS, kiểm tra CA/hostname; HTTP chỉ DEBUG + LAB loopback. CIDR, DNS và đích socket được pin qua transport dùng chung S2. Không proxy môi trường, redirect, URL hoặc PromQL từ browser. Bearer token chỉ đọc từ biến môi trường phía server, không được trả về client.
- Tối đa 100 profile, 500 node/vector, 16 tên metric, bốn query đồng thời, body512KiB/query, timeout và deadline đọc. Vector thiếu, trùng, khác scope, không finite hoặc sai miền giá trị bị từ chối. Timestamp nguồn phải còn hạn và không đi lùi.
- Generation/profile revision/fingerprint chặn kết quả cũ. Claim khóa cluster rồi snapshot; publish khóa snapshot. Không giữ transaction khi chờ HTTP. Profile thay đổi đòi revision tăng.
- Thiếu dữ liệu, lỗi collector hoặc mẫu hết hạn => Unknown, giữ số đo cuối kèm stale/source/observed_at/last_success_at. Không biến thiếu dữ liệu thành0 hoặc Offline. Node chỉ Healthy khi MinIO + host up cùng current và cluster không có điều kiện suy giảm.
- Incident được dedupe theo cluster/code khi còn active. ACK có version, actor/time/reason và audit, không đóng incident. Mẫu mới xác nhận hồi phục mới resolve. Thu hồi quyền được kiểm tra lại khi ACK; quyền view/configure riêng không tự cho monitor.
- SSE chỉ khả dụng với ASGI và DB/cached-DB sessions. Stream hữu hạn, kiểm tra session/password hash/quyền mỗi5s, cursor đúng cluster, heartbeat, no-store/no-transform. Không token trên URL. WSGI trả snapshot với sse_available=false; stream503, UI polling30s. Browser vẫn kiểm tra hết hạn theo đồng hồ khi mất mạng.
- Telemetry cập nhật data card; không remount canvas, đổi vị trí hay ghi layout. Mọi cờ rollout và thao tác node/pool giữ OFF.

## Giới hạn và gate

Chưa có profile query đã duyệt trên provider thật, chưa chứng minh quorum/host/metrics thực, collector process deployment, TSDB retention, SSE qua reverse proxy hoặc tải nhiều client. G2/G4 vẫn mở. Không thêm cài đặt ASGI server, notification/email, agent enrollment hay thao tác hạ tầng. Lịch sử incident có REST phân trang; UI hiện tập trung active incidents, không triển khai biểu đồ lịch sử raw metric.

Đối chiếu: [Prometheus HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/), [timestamp()](https://prometheus.io/docs/prometheus/latest/querying/functions/#timestamp), [Django StreamingHttpResponse](https://docs.djangoproject.com/en/5.2/ref/request-response/#django.http.StreamingHttpResponse).
