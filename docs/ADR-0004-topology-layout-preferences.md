# ADR-0004 — Topology canvas và layout preference

Ngày: 09/11/2026. Trạng thái: triển khai mã S3, rollout mặc định OFF; G2 MinIO thật còn mở.

## Vấn đề và lựa chọn

Inventory S1 đã có cluster/pool/node/disk và layout cá nhân/dùng chung, nhưng chưa có canvas hay API lưu layout. Việc dùng chung revision cho trạng thái thiết bị và tọa độ sẽ làm mất bố cục khi dữ liệu mới đến. Kéo node sang một vị trí khác cũng không được biến thành lệnh chuyển máy chủ giữa pool.

Giống bản đồ kho trên giấy: dịch ô ghi tên một kệ giúp đọc bản đồ dễ hơn; không phải lệnh di chuyển kệ thật.

Giữ models hiện có, thêm PATCH layout, dùng `@xyflow/react`12.12.1 đã pin và kiểm tra MIT/React peer dependencies. Không thêm engine auto-layout: quan hệ hiện tại là pool chứa node nên grid xác định đủ dùng. Không thêm bảng, migration, backend service hoặc bộ theme mới.

## Hai loại revision

Snapshot giữ revision topology và các revision layout riêng. GET chọn layout cá nhân trước, nếu chưa có thì dùng shared default; response trả thêm `layout_revisions:{personal,shared}` để save đúng đích, kể cả khi đang kế thừa shared.

PATCH chỉ nhận `{scope,expected_revision,positions,viewport}`. Positions chỉ có UUID node trong cluster và x/y finite; viewport có x/y/zoom giới hạn. Body không nhận pool, hostname, endpoint hoặc thao tác quản lý. Không đổi inventory, binding hay gọi storage.

Có view grant thì lưu layout của chính mình. Shared default cần thêm storage.configure; Platform giữ policy Super Admin của S2. Save recheck quyền dưới khóa tenant/user/cluster; race hai cửa sổ từ cùng revision chỉ có một thay đổi thắng. Retry cùng nội dung là no-op. Shared save có audit; preference cá nhân không làm nhiễu audit hạ tầng.

## Hiển thị và tương tác

`StorageManager` dùng chung giữa Platform/Organization, gắn topology vào bộ chọn cluster và Connections S2. Cờ `SECUREDRIVE_STORAGE_TOPOLOGY_ENABLED` độc lập, mặc định false; cần control center cũng bật. Không bật cờ trong `.env` khi triển khai code.

React Flow nằm trong client boundary, lazy load và giữ nodeTypes ổn định. Parent group là pool inventory, node không thể đổi parent bằng kéo thả. Line chỉ biểu diễn membership, không suy ra liên kết mạng vật lý. Drag không ghi API; người dùng chọn Save layout. Layout chưa lưu chặn đổi cluster/section, có Discard rõ ràng và cảnh báo khi rời trang.

Canvas có pan/zoom/fit/mini-map, grid auto layout, tìm/lọc, chọn card, List view và điều khiển dịch vị trí bằng bàn phím. Inspector hiện ngay từ snapshot rồi tải chi tiết scoped, hủy request khi đổi node. Desktop dùng panel; màn hình hẹp dùng native Dialog. Sửa chung Dialog để đóng và trả focus về điểm mở khi unmount.

Health/source lấy từ API; khi chưa có collector vẫn Unknown/not_collected. CPU/RAM/uptime không hiện số giả. Disk capacity ghi rõ nguồn inventory. Snapshot quá giới hạn chuyển sang node list phân trang; không dựng map bị cắt thiếu dữ liệu.

## Giới hạn và rollout

Đây là bước mã giao diện/metadata an toàn theo yêu cầu tiếp tục. Không coi G2 vận hành đã được duyệt; không bật probe/routing, không cài MinIO, không triển khai node/agent. G2 thật, owner review S3 và các gate S4–S8 còn độc lập.

Vị trí node được lưu tương đối trong pool; kích thước pool do grid xác định. Nếu inventory đổi làm vị trí cũ nằm ngoài group mới, renderer giới hạn vị trí và báo đã điều chỉnh. Shared default không ghi đè preference cá nhân có sẵn. Không có quy trình physical planning hoặc shared realtime editing trong S3.

Đối chiếu: [React Flow node/parentId](https://reactflow.dev/api-reference/types/node), [React Flow12 migration](https://reactflow.dev/learn/troubleshooting/migrate-to-v12), [giấy phép và nguồn upstream](https://github.com/xyflow/xyflow). Kiểm tra cuối dựa trên package đã cài cùng compiler/browser, không suy tương thích chỉ từ tài liệu.
