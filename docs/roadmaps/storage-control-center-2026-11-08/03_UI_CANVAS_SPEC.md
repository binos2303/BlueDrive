# 03 — UI/UX Specification: Interactive Topology Canvas

## 1. Route plan
- Platform: giữ `/admin/infrastructure/topology`, hiển thị cluster thuộc Platform context.
- Organization: bổ sung route trong `/organization/admin/.../storage` (chọn URL phù hợp hiện hữu, tránh overlap dynamic route). Dùng chung `<StorageManager scope=...>`.
- Tab header: **Topology | Nodes | Disks | Operations | Metrics | Settings**; Canvas là tab mặc định. Danh sách bảng là alternative accessibility/operations, không phải home.

## 2. Desktop layout
```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Organization / Storage > Cluster A          HEALTH: UNKNOWN   [Refresh]       │
│ [Topology] [Nodes] [Disks] [Operations] [Metrics]             [+ Register]     │
├──────────────────┬────────────────────────────────────────┬───────────────────┤
│ Inventory/Search │ [Fit] [Auto layout] [Zoom] [Mini map]  │ Node Inspector    │
│ Available hosts  │  Cluster A                              │ Node 02           │
│ Unassigned hosts │    └ Pool 1                            │ IP / agent ID     │
│ Pools            │      ├ Node 01 (Healthy)               │ Last seen         │
│ Filters          │      ├ Node 02 (Warning) [SELECTED]    │ CPU/RAM/Disk      │
│                 │      └ Node 03 (Unknown)                │ Disks / metrics   │
│ Drag host here   │                                        │ Events / Manage   │
└──────────────────┴────────────────────────────────────────┴───────────────────┘
```

## 3. Node card
- Hostname/alias (1–2 lines), managed UUID short, IP/DNS, process status, node status, CPU/RAM/drive summary, last seen.
- Status labels `HEALTHY | DEGRADED | CRITICAL | OFFLINE | UNKNOWN | MAINTENANCE`, kèm icon không chỉ màu.
- Dữ liệu thiếu hiện `—`, không hiển thị 0% hoặc `Healthy` giả.
- Group node theo pool; line edges thể hiện **quan hệ topology**. Mạng vật lý là layer tách riêng (đừng ngầm suy physical links).

## 4. Interaction matrix
| Hành động | View mode | Plan mode | Tác động hạ tầng |
|---|---|---|---|
| Drag node trong canvas | Chỉ tọa độ UI | Chỉ tọa độ UI | Không |
| Click node | Open right inspector | Open right inspector | Không |
| Multi-select | Summary; filter logs | Plan target selection | Không |
| Drag unassigned host vào pool | Không | Draft change plan | Không đến khi approve + job |
| Add node từ sidebar | Open enrollment | Create draft only | Không |
| Remove node card | Hide from view (không delete) | Request retirement workflow | Không trực tiếp |
| Save layout | Lưu X/Y/zoom theo viewer hoặc tổ chức | Tương tự | Không |
| Apply plan | Ẩn | Explicit confirm, preflight, approval | Có, qua job |

## 5. Node inspector tabs
- Overview: node ID, name, node IP, OS, agent version, MinIO release, last seen, status source, process uptime.
- Disks: path/disk ID, capacity, free, I/O, healing, alerts; quyền admin không có nghĩa có quyền format.
- Performance: CPU/RAM/host network, MinIO request rate/errors + time range, source timestamp.
- Events: history theo node/cluster và operation id; audit có actor và before/after.
- Management: Rename label, connection diagnostics, enter maintenance, replace, remove from inventory; destructive buttons có explain risk, RBAC gate.

## 6. Responsive & keyboard
- >=1024px ba vùng; 768–1023px inspector Drawer; <768px canvas full width, inventory/inspector bottom sheet.
- Keyboard: Tab đến node, Enter/Space select, Esc dismiss, arrow pan/navigation alternative, `List view` thao tác tương đương; touch drag dùng Pointer Events.
- WCAG AA focus, tooltip accessible, không rely on hover. Khi streaming updates không tự chuyển focus, không đè layout đang kéo.
- Empty (no cluster), loading, partially connected, stale metrics, offline, permission denied, request conflict đều có trạng thái riêng.
- Layout persistence là preference, không gây 409 khi telemetry tick cập nhật.

## 7. Component architecture & state
- `StorageManager` nắm scope and cluster selection.
- `TopologyCanvas` dùng `@xyflow/react` ở client-only boundary; `nodeTypes` stable, memo custom node, event handling, controlled state.
- `useStorageTopology` fetch one snapshot (cluster/pools/nodes/disks) phiên bản topology `revision`.
- `useStorageTelemetry` fetch summary and optional SSE; telemetry state giữ riêng khỏi topology/layout để tránh re-render mọi edge khi CPU tick.
- `NodeInspector` query details riêng khi selected node; cancel stale requests on selection change.
- Use `etag/revision` for saving layout and plans; update counters independent from UI position.

## 8. UX acceptance
- Canvas có 1, 10, 50, 100 nodes; zoom/fit/drag không giật đến mức ảnh hưởng thao tác, đo trên hardware xác định.
- Node click -> inspector trong 250ms (state local, API details async); mất API hiện dữ liệu cũ kèm `Stale`, không tự reset selection.
- Drag position -> reload preserved; không mutation topology; chặn accidental save while editing.
- 320px width + 200% zoom; keyboard list view, touch behavior on phone thật.
- 100% health badges xuất phát từ metrics/agent hoặc `UNKNOWN`, không placeholder giả.
