---
name: bluedrive-api-review
description: Review BlueDrive Django API changes for authentication, tenant and workspace isolation, quota integrity, races and compatibility. Use for API/security review or a change crossing these boundaries; ordinary UI or documentation edits do not need this workflow.
---

# Review API và quyền BlueDrive

## Mục tiêu và khi dùng

Tìm lỗi có thể chứng minh trên luồng API đã thay đổi, đặc biệt khi quyền, quota hoặc worker tham gia. Dùng khi review API/backend hoặc sửa hành vi chạm các ranh giới này. Skill này không tự cấp quyền sửa code, chạy live tests hoặc thay dữ liệu.

Đọc [AGENTS.md](../../../AGENTS.md), phần backend/tests trong [MAP.md](../../../MAP.md), diff hiện tại và [chu trình phát triển](../../../docs/DEVELOPMENT.md#7-engineering-harness).

## Quy trình

1. Chốt phạm vi diff và callers. Đi từ `backend/securedrive/urls.py` → `urls.py` của app → view/API → access/service/model/constraint; đối chiếu frontend service đang gọi. Đừng coi đề xuất `/api/v1` là route đã triển khai.
2. Lập ma trận actor/thao tác/đích: anonymous, user inactive, owner, viewer/editor/admin, membership bị thu hồi, Workspace khác và Tenant khác. Tái sử dụng `accounts/access.py`, `sharing/services.py`/`policy.py`; Platform admin không tự có quyền Organization storage hoặc nội dung.
3. Theo dấu nguồn của owner, Tenant, Workspace, object key, profile và quota. Header chọn Workspace chỉ chọn context. Kiểm tra server chống IDOR/cross-tenant, session/CSRF, field allowlist và phản hồi không lộ dữ liệu/URL/secret.
4. Nếu chạm upload/quota, theo `files/quota.py` và `finalization.py`: admission đồng thời, reservation consumed/released đúng một lần, retry/abort/expire, mất quyền trước publication, worker claim/attempt và stale result. Kiểm tra lock order, giới hạn RPC trong transaction và lỗi sau khi object store thành công nhưng DB chưa commit; không mặc định DB/S3 atomic.
5. Nếu chạm storage target, đối chiếu ADR-0003: upload/location ghim revision, worker/download/cleanup giữ cùng target; tắt routing không được chuyển dữ liệu đã ghim về global factory. Giữ AES legacy và compatibility layer khi chưa có migration được duyệt.
6. Đọc query theo đường nóng: pagination/bounds, `select_related`/`prefetch_related`, N+1, memory và retry/timeout; kiểm tra audit/response/error có giữ scope và không che failure. Migration cần nêu ảnh hưởng dữ liệu, constraint và rollback/forward-fix.
7. Chọn test liên quan theo bảng trong DEVELOPMENT; lỗi quyền cần bài âm chéo scope/thu hồi quyền, lỗi race cần tái hiện trạng thái hoặc concurrent admission, không chỉ happy path. Dùng runner DB riêng hiện có; không sửa assertion để khớp hành vi sai.

## Hoàn thành và báo cáo

Review hoàn thành khi các đường vào bị tác động và ma trận quyền liên quan đã được đối chiếu, test có bằng chứng hoặc blocker rõ, diff được đọc lại. Không có findings không đồng nghĩa runtime/production được chứng nhận.

Báo findings theo mức độ, `file:line`, trigger/actor, ảnh hưởng và cách tái hiện/test; tách lỗi đã chứng minh khỏi nghi vấn cần xác minh. Ghi PASS/FAIL/SKIP/BLOCKED cho từng nhóm kiểm tra, lệnh đã chạy, phần thiếu và rủi ro còn lại. Nếu chỉ được yêu cầu review, báo kết quả trước khi tự biến review thành refactor.
