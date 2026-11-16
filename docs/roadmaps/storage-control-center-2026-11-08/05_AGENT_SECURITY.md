# 05 — Enterprise Agent: architecture, enrollment, security

## 1. Scope of trust
Enterprise machines nằm trong mạng tổ chức, Platform bên ngoài không có quyền shell/root mặc định. Agent triển khai tối thiểu, chủ động mở kết nối outbound HTTPS/mTLS; Platform chỉ phát hành tác vụ trong allowlist, doanh nghiệp phê duyệt các tác vụ nguy hiểm.

## 2. Enrollment protocol
1. Organization Storage Admin tạo `enrollment_request` cho host inventory với TTL, max_uses=1, bound tenant/cluster/node.
2. Admin trên host chạy installer do doanh nghiệp kiểm chứng checksum/signature; không paste token vào shell history nếu có lựa chọn secret stdin/file permission 0600.
3. Agent sinh keypair thiết bị ở host, gửi public key/certificate request cùng token qua TLS đến enrollment endpoint.
4. Platform kiểm tra single-use token, quyền, tenant, host identity; phát cert ngắn hạn, ghi audit; không lưu private key thiết bị.
5. Agent xác minh server identity và policy; kết nối mTLS, dùng heartbeat sequence + monotonic operation generation.
6. Rotate cert tự động, revoke host khi mất máy; event/replay protection, token không tái sử dụng.

## 3. Task allowlist (NO arbitrary shell)
- `collect_host_facts`, `check_disk_health`, `check_minio_health`, `verify_network`, `validate_prerequisites`.
- Sau S6 mới bật `install_pinned_package`, `configure_minio`, `start_service`, `stop_service_if_safe`, `replace_node`, `expand_pool`.
- Each task includes signed plan digest, resources allowlist, expected generation, TTL, dry_run, approval ID, allowed paths, max duration. Agent xác nhận cả local organization policy.
- Agent chạy user ít quyền; elevated helper chỉ dùng action được khai báo và polkit/sudo allowlist; không chuyển SSH password/root token qua Platform.
- Disk operations không tự format. Mỗi disk phải có stable ID, expected clean signature và explicit confirmation. Deny on mismatch.

## 4. Secure communications / SSRF
- Never let Django connect to arbitrary `http://<user IP>` from form without allowlist, DNS validation, private/loopback address protections appropriate to scope, redirect disabled, TLS hostname check; prefer agent to probe local endpoints.
- Enforce mTLS or pinned agent identity; supported TLS policy; per-tenant credentials and short-lived tokens. Connection retries bounded and jittered.
- UI never exposes admin S3 credentials; public presigned URLs short lived and scoped to bucket/key/version/verb with safe browser reachability.
- Separate keys: MinIO root/admin, operations-agent identity, S3 app access/secret, monitoring read-only identity. Rotate and audit.

## 5. Fail-closed semantics
- Platform lost contact -> dashboard `UNKNOWN`, **not** `OFFLINE` or `HEALTHY`.
- Expired approval -> fail operation. Agent must fetch latest tenant policy before any irreversible step.
- Conflicting job -> reject / queue, do not parallel restart/expand/decommission for same cluster.
- No preview of secret values; logs redact signed URLs, credentials, cookies and enrollment tokens.
- Long-running jobs resume from durable checkpoints and verify desired vs actual state; no blind retry of irreversible operations.

## 6. Critical tests
- Cross-tenant enrollment/replay; hostname/IP swapping; body tampering; agent cert revoke; bad time skew; duplicate delivery; response lost after mutation; concurrent approvals; partial disk preflight.
- Agent running after org suspend; disabled node credential; stale approval; aborted UI request cannot cancel already started physical I/O (report NEEDS_ATTENTION).

## 7. Ownership note
Nếu metadata vẫn ở Platform, dữ liệu tên file, folder, quyền và audit vẫn thuộc tầng quản lý trung tâm. Nếu yêu cầu doanh nghiệp giữ *tất cả* metadata, on-prem control plane phải là một dự án riêng, không thể được thực hiện chỉ bằng đổi S3 endpoint.
