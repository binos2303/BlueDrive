# 10 — Architecture decisions, trade-offs, open risks

## ADR-001 — Một UI chung cho Platform và Organization
**Decision:** một `StorageManager` với context quyền khác nhau, không duplicate pages/logic. **Why:** UX nhất quán, dễ bảo trì. **Risk:** nhầm scope; backend bắt buộc enforce tenant filters. **Alternative:** hai ứng dụng hoàn toàn riêng (bác bỏ do trùng code).

## ADR-002 — Canvas layout tách khỏi topology
**Decision:** drag chỉ ghi `TopologyLayout`; thay đổi physical qua `ClusterOperationJob`. **Why:** tránh kéo nhầm khiến cluster lỗi. **Alternative:** direct drag-to-deploy (bác bỏ vì nguy hiểm).

## ADR-003 — Connect existing trước auto-deploy
**Decision:** read-only/verified S3 trước agent; provisioning sau. **Why:** giảm rủi ro, reuse adapter; có telemetry thật sớm. **Cost:** phải onboarding cluster có sẵn trong demo.

## ADR-004 — Agent outbound, no arbitrary SSH
**Decision:** đăng ký agent với danh tính máy và allowlisted operations. **Why:** doanh nghiệp sau NAT, giới hạn đặc quyền, giảm SSRF/lateral movement. **Cost:** xây lifecycle/cert/upgrade agent.

## ADR-005 — Binding bất biến cho phiên upload
**Decision:** pin provider khi UploadSession init; read file qua StorageLocation. **Why:** tránh thay active cluster giữa upload. **Cost:** migration/fallback for legacy sessions.

## ADR-006 — Timeseries riêng, PostgreSQL giữ current inventory
**Decision:** Prometheus/TSDB cho raw metrics, PostgreSQL snapshot/status/audit. **Why:** tránh DB tăng vô hạn; **Cost:** vận hành collector mới.

## ADR-007 — MinIO edition/version policy
**Decision:** không xây installer chung khi chưa chốt license/release. MinIO Community archived (2026) và AIStor khác edition/terms. **Why:** công việc triển khai enterprise có ràng buộc vận hành/pháp lý. **Cost:** lập runbook tương ứng phiên bản.

## ADR-008 — Business quota thuộc Organization
**Decision:** Owner/Admin tự quản lý tenant/workspace/member quota; Platform không mặc định đặt cap doanh nghiệp trên storage họ sở hữu. Physical capacity ≠ logical quota. **Why:** phản ánh mô hình enterprise self-hosted. **Cost:** integrity với concurrent reservations.

## Critical risks and owners (TBD)
| ID | Risk | Mitigation / acceptance |
|---|---|---|
| R1 | MinIO version/LICENSE không cho automated redistribution | Chốt edition, contract, pin artifact trước S6 |
| R2 | Browser không truy cập được private S3 endpoint | VPN/gateway/LB + reachability test, no public node IP assumption |
| R3 | SSRF thông qua IP/URL admin cung cấp | agent probe + allowlist, TLS, no redirects |
| R4 | Cross-tenant metadata/metrics leak | scoped APIs + query filters + tests |
| R5 | Rotate endpoint khi session upload đang chạy | pinned config, versioned secrets |
| R6 | Mất telemetry bị hiểu nhầm server hỏng | UNKNOWN + source/time + multi-signal |
| R7 | Erasure/quorum invalid after node deletion | version-aware preflight, deny direct delete |
| R8 | Quota/physical mismatch | logical quota service + physical provider metrics riêng |
| R9 | Raw credentials leak | secrets store + rotate + redact logs + no plaintext |
| R10 | Thêm nhiều UI panels vượt mức cần | MVP canvas/inspector only, follow evidence |
| R11 | Data migration giữa clusters làm mất VersionId | explicit migration job + mapping + checksum |
| R12 | Agent compromised as remote execution platform | allowlist signed tasks, least privilege, audit, cert revocation |

## Chưa chốt (không nên tự giả định)
- Doanh nghiệp có dùng một hay nhiều cluster ngay trong MVP? Khuyến nghị **1 active cluster** ban đầu.
- Bản MinIO đang dùng được phép phân phối/cài tự động cho khách? Cần xác nhận.
- Metadata doanh nghiệp tiếp tục ở PostgreSQL Platform hay có yêu cầu on-prem hoàn toàn? Kế hoạch này giả định **control plane trung tâm**.
- Agent hỗ trợ Linux trước hay thêm Windows? Khuyến nghị Linux/Ubuntu Server đầu tiên.
- Platform có cần hỗ trợ cluster tenant qua grant có thời hạn? Khuyến nghị có, mặc định không.
