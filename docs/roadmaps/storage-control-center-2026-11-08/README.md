# BlueDrive — Storage Control Center: triển khai từ A đến Z

> **Roadmap lịch sử ngày 08/11/2026.** Từ 16/11/2026, [ADR-0010](../../ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md) thay đích MinIO/cutover bằng SeaweedFS-only, Enterprise My Drive và CSE/recovery. [P0 baseline và backlog P1–P8](../../REFACTOR_P0_BASELINE_2026-11-16.md) là điểm bắt đầu hiện hành; các phase/agent prompts bên dưới không tự cấp quyền triển khai hoặc vận hành.

**Ngày lập:** 08/11/2026 · **Trạng thái:** KẾ HOẠCH / chưa triển khai mã · **Nguồn:** `BLUEDRIVE_SOURCE_AUDIT_SAFE.zip` + tài liệu nhà cung cấp được đối chiếu.

## Mục tiêu thống nhất
- Platform tạo Organization và cấp Owner/Admin; người dùng không tự tạo Organization.
- Organization có quyền tự đăng ký, vận hành và quản lý quota trên hạ tầng lưu trữ thuộc tổ chức.
- Platform có Storage Manager cho **storage của Platform**; Organization có Storage Manager cho **cluster thuộc tổ chức**; tái sử dụng đúng một design system và backend policy.
- Giao diện chính là **React Flow topology canvas**; kéo thả vị trí, click mở Node Inspector; dữ liệu trạng thái là telemetry thật, có `observed_at`, phân biệt Offline với Unknown.
- Có 3 luồng: **Connect Existing Cluster** (đầu tiên), **Register Host/Agent**, **Deploy New Cluster** (sau cùng). Node CRUD inventory KHÔNG đồng nghĩa sửa topology live.
- Giữ Django + PostgreSQL + Next.js + MinIO adapter; không thêm microservices/Kubernetes chỉ để tăng độ phức tạp.

## Tải đọc theo thứ tự
1. `01_MASTER_PLAN.md` — nhiệm vụ, thứ tự và go/no-go.
2. `02_ARCHITECTURE_SOURCE_MAP.md` — đối chiếu source gốc và thiết kế đích.
3. `03_UI_CANVAS_SPEC.md` — yêu cầu giao diện và trải nghiệm kéo thả.
4. `04_DOMAIN_AND_API.md` — ERD logic, schema/API mẫu, tương thích dữ liệu.
5. `05_AGENT_SECURITY.md` — agent, danh tính, RBAC, secret management.
6. `06_PROVISIONING_OPERATIONS.md` — connect, preflight, deploy, expand, remove.
7. `07_MONITORING.md` — node/drive/cluster, alerts, real-time status.
8. `08_QA_ACCEPTANCE.md` — QA, fault injection, KPI và điều kiện nghiệm thu.
9. `09_CODEX_PROMPTS.md` — prompt giao Codex theo sprint, có guardrails.
10. `10_ADR_AND_RISKS.md` — quyết định, trade-offs, vấn đề chưa chốt.
11. `SPRINT_BACKLOG.csv` — bảng nhập vào Excel/Trello/Jira.
12. `agent-skill/SKILL.md` — quy trình tái sử dụng để vận hành kiểm toán/triển khai.

## Các gate không được bỏ qua
- **G0**: repository sạch, test baseline, snapshot dữ liệu test, xác nhận tenant roles.
- **G1**: đọc được dữ liệu cluster thật, không tác động storage.
- **G2**: tenant isolation + browser-accessible endpoint + credentials ở vùng tin cậy.
- **G3**: telemetry có nguồn + thời điểm quan sát; Unknown khi stale.
- **G4**: agent enrollment và RBAC được kiểm tra độc lập; không remote arbitrary shell.
- **G5**: deployment chỉ sandbox; license/version/topology hợp lệ và explicit approval.
- **G6**: lỗi node / mất quorum / rollback không dẫn đến xóa dữ liệu hoặc báo thành công giả.

## Chưa được phép khẳng định
Đây là **bộ triển khai theo giai đoạn**, không phải source code đã triển khai. Chưa chứng nhận MinIO hiện tại, email thực, backup thực, TLS/SSE thực, multi-node worker, hoặc HA production. Phải xác minh môi trường thực tế trước khi kích hoạt thao tác hạ tầng.

## Quy tắc an toàn file nguồn
Không đưa ZIP source vào bộ hướng dẫn này. Bản `BLUEDRIVE_SOURCE_AUDIT_SAFE.zip` từng chứa đường dẫn `source\\frontend\\.cache\\storage-tools\\mc-config\\config.json` và `source\\frontend\\playwright\\.auth\\admin.json`. Hãy kiểm tra có thông tin đăng nhập/session thật không; nếu có, thu hồi/rotate trước khi chia sẻ. Không dùng script quét tên file như cơ chế xác nhận an toàn duy nhất.

## Tham chiếu chính
- https://docs.min.io/aistor/operations/scaling/
- https://docs.min.io/aistor/operations/scaling/expansion/
- https://docs.min.io/aistor/operations/monitoring/healthcheck-probe/
- https://docs.min.io/aistor/operations/monitoring/metrics-and-alerts/
- https://docs.min.io/aistor/installation/linux/install/
- https://reactflow.dev/examples/interaction/drag-and-drop
- https://prometheus.io/docs/guides/node-exporter/
- https://www.min.io/legal

Các tài liệu của MinIO Community cũ và AIStor hiện tại **không thay thế nhau**. Chọn edition/version rồi pin runbook đúng edition trước khi điều phối deployment.
