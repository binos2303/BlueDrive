# 06 — MinIO cluster provisioning, lifecycle and operations runbook

## A. Supported modes
1. **Connect existing cluster** — S2, ưu tiên đầu tiên, read-only discovery rồi verify S3 sandbox.
2. **Register Enterprise host** — S5, thu thập facts, không đụng MinIO đang chạy.
3. **Deploy new cluster** — S6, chỉ trong lab/staging đã xác minh version/license/topology.
4. **Scale/replace/decommission** — S7, cần riêng kế hoạch/approval và preflight read/write quorum.

## B. Connect-existing wizard: từng bước
- Chọn organization scope & cluster display name.
- Khai báo public S3 endpoint qua DNS/TLS, internal endpoint do agent xác minh, edition/release; không mặc định public endpoint là từng node.
- Tạo `credential_ref` từ secret store; không lưu raw secret trong DB/log.
- Read-only health probe, validate TLS, S3 ListBuckets/HeadBucket theo least privilege; đọc cluster metrics nếu quyền.
- Probe isolated temporary object trong bucket TEST mới khi được ủy quyền; PUT/GET checksum/DELETE; verify browser reachability từ mạng thử nghiệm.
- Ghi cluster ACTIVE chỉ nếu tất cả kiểm tra bắt buộc đạt; nếu không `DEGRADED/UNVERIFIED` với lý do.

## C. New-cluster wizard
1. `DRAFT`: chọn edition/version/mode (single-node demo hay distributed), license review.
2. `ENROLL`: đăng ký Agent trên các VM/host; không cho remote unauthenticated IP.
3. `DISCOVER`: thông số CPU/RAM/NIC/disks, lỗi S.M.A.R.T, máy đang có MinIO service không.
4. `PREFLIGHT`: cảnh báo OS, firewall, DNS, TLS, ulimit, time sync, paths, drives, capacity planning, valid erasure sets, failure domains.
5. `PLAN`: trên canvas kéo **inventory host** vào pool nháp, visual simulation; không thay topology thật.
6. `REVIEW`: bảng diff desired/actual, predicted outage, risk, approvals, rollback/compensation, explicit version pin.
7. `EXECUTE`: backend `ClusterOperationJob` + Agent allowlisted steps, checkpoint, lease/fencing.
8. `VERIFY`: read/write quorum, S3 test bytes/hash, versioning/SSE policy, metrics, backup config.
9. `BIND`: chỉ liên kết cluster với Organization khi health & policy hợp lệ, không chuyển object cũ tự động.
10. `MONITOR`: bật alerts, handover runbook và test failover khi môi trường cho phép.

## D. Node lifecycle semantics
| User action | DB action | Real MinIO operation | Safety |
|---|---|---|---|
| Register host | New pending inventory | None | Enrollment + host identity |
| Drag node in canvas | Update `TopologyLayout` | None | No topology mutation |
| Drop host into draft pool | New draft plan | None | Validate node and pool constraints |
| Edit label | Update display metadata | None | Audit changes |
| Edit IP | Changes endpoint draft | Depends on version/topology | Revalidate agent identity/TLS/cluster config |
| Remove unused host | Inventory retire | None | Must not be member/hold data |
| Replace failed member | Durable operation job | Version-specific replacement | Quorum/health/backup preflight |
| Expand | Durable operation job | **Add server pool** | Compatible erasure settings/edition |
| Remove active pool | Decommission job | Version-specific pool decommission | Enough capacity and verified cleanup |

## E. MinIO edition/version-specific guardrail
- MinIO Community Github repository archived 25/04/2026; AIStor docs reflect another product and license. Do not use AIStor commands to automate old Community version without validating compatibility.
- For AIStor distributed production, current guidance recommends at least 8 dedicated hosts; small 1–4 VM configuration must be explicitly tagged `LAB`, not production HA claim.
- AIStor horizontal expansion through **new server pool**, not arbitrary additional disk/node to existing pool. Decommission requires >=2 pools, adequate free capacity and verified object migration.
- Current AIStor versions may support pool hot-reload in specific versions/configs; other cases require coordinated process restart. Thus every operation must dispatch through version-aware adapter, never generic rolling restart.
- Maintain no more than ~70% target capacity as planning guidance, not hardcode global storage quota.

## F. Failure cases and recovery
- Agent disconnected during install: mark job `UNKNOWN/NEEDS_ATTENTION`; re-read actual state before retry.
- Node failed before cluster ready: no ACTIVE; preserve detailed logs; recover only immutable completed steps.
- S3 PUT succeeded but ACK lost: HEAD exact object/version/checksum before retry; prevent duplicate namespace writes.
- `StorageBinding` switch while upload ongoing: session pinned storage config, old upload completes on old target; forbid forced switching for active session.
- Container/VM restarted: reconcile job generation and actual process/status; no repeated disk formatting.
- Aborted deletion/decommission: stop further irreversible actions; back up metadata/settings, inspect object state, manual recovery playbook.

## G. No automatic destructive scripts in this package
Không kèm lệnh format disks, xóa pool, gọi `mc admin decommission` trên cluster của người dùng. Trước khi viết runbook thực thi cần biết edition, release, topology, backup, drive layout, quyền và phiên bản `mc` tương thích.
