"use client";

import { memo, useEffect, useMemo, useRef, useState } from "react";
import { ReactFlow, MiniMap, Handle, Position, applyNodeChanges, type NodeProps, type ReactFlowInstance } from "@xyflow/react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, CircleHelp, GripHorizontal, Minus, Plus } from "lucide-react";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { storageWrite, type StorageLayout, type StorageTopologySnapshot, type StorageTelemetry } from "@/lib/storage-control-service";
import { nodeTelemetryHealth } from "./telemetry-model";
import { HOST_HEIGHT, HOST_WIDTH, layoutPositions, topologyGraph, type HostFlowNode, type PoolFlowNode, type StorageFlowNode } from "./topology-model";
import styles from "./TopologyCanvas.module.css";
import "@xyflow/react/dist/style.css";

const HostCard = memo(function HostCard({ data }: NodeProps<HostFlowNode>) {
  return <><Handle type="target" position={Position.Top} isConnectable={false} /><div className="storage-drag-handle flex h-11 cursor-grab items-center justify-between gap-2 border-b border-border px-3 active:cursor-grabbing" title="Drag to arrange this card"><span className="truncate text-sm font-semibold">{data.inventory.hostname}</span><GripHorizontal size={18} className="shrink-0 text-muted" /></div><button type="button" className="nodrag nopan block w-full space-y-2 rounded-b-xl px-3 py-3 text-left" aria-label={`Inspect ${data.inventory.hostname}`} onClick={() => data.inspect(data.inventory.id)}><span className="block truncate text-xs text-muted">{data.inventory.private_ips.join(", ") || "IP not reported"}</span><span className="flex items-center gap-1.5 text-xs"><CircleHelp size={14} /><span>Health: {data.inventory.health.status}</span></span><span className="block text-xs text-muted">{data.diskCount} recorded disks · {data.inventory.inventory_status}</span></button></>;
});
const PoolCard = memo(function PoolCard({ data }: NodeProps<PoolFlowNode>) { return <><div className="flex items-center justify-between gap-3 px-5 py-3 text-sm"><span className="truncate font-semibold">{data.label}</span><span className="shrink-0 text-xs text-muted">{data.count} nodes</span></div><Handle type="source" position={Position.Bottom} isConnectable={false} /></>; });
const nodeTypes = { host: HostCard, pool: PoolCard };

export default function TopologyCanvas({ snapshot, telemetry, tenantId, canConfigure, onInspect, onDirtyChange, queryIds }: {
  snapshot: StorageTopologySnapshot; telemetry?: StorageTelemetry | null; tenantId?: string; canConfigure: boolean;
  onInspect: (id: string) => void; onDirtyChange: (dirty: boolean) => void; queryIds: Set<string>;
}) {
  const graph = useMemo(() => topologyGraph(snapshot, onInspect), [snapshot, onInspect]);
  const [nodes, setNodes] = useState<StorageFlowNode[]>(graph.nodes);
  const baseline = useRef(snapshot.layout);
  const [flow, setFlow] = useState<ReactFlowInstance<StorageFlowNode> | null>(null);
  const [dirty, setDirty] = useState(false);
  const [scope, setScope] = useState<"personal" | "shared">("personal");
  const [revisions, setRevisions] = useState(snapshot.layout_revisions);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [discard, setDiscard] = useState(false);
  const [arrange, setArrange] = useState("");
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const confirm = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", confirm);
    return () => window.removeEventListener("beforeunload", confirm);
  }, [dirty]);
  const rendered = useMemo(() => nodes.map((node) => node.type === "host" ? { ...node, hidden: !queryIds.has(node.id), data: telemetry ? { ...node.data, inventory: { ...node.data.inventory, health: nodeTelemetryHealth(telemetry,node.id) } } : node.data } : { ...node, hidden: !snapshot.nodes.some((host) => `pool:${host.pool_id ?? "unassigned"}` === node.id && queryIds.has(host.id)) && node.data.count > 0 }), [nodes, queryIds, snapshot.nodes, telemetry]);
  function changed() { setDirty(true); setNotice(""); }
  async function save() {
    if (!flow || savingRef.current) return;
    savingRef.current = true; setSaving(true); setError(""); setNotice("");
    try {
      const result = await storageWrite<{ layout: StorageLayout }>({ tenantId }, `clusters/${snapshot.cluster_id}/layout/`, { scope, expected_revision: revisions[scope], positions: layoutPositions(nodes), viewport: flow.getViewport() }, "PATCH");
      setRevisions((current) => ({ ...current, [scope]: result.layout.revision }));
      baseline.current = result.layout;
      setDirty(false);
      setNotice(scope === "shared" ? "Shared layout saved. Viewers with a personal layout keep their own positions." : "Your layout was saved. Storage inventory and connections are unchanged.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save layout. Your changes are still here."); }
    finally { savingRef.current = false; setSaving(false); }
  }
  function shift(dx: number, dy: number) {
    setNodes((current) => current.map((node) => {
      if (node.id !== arrange || node.type !== "host") return node;
      const parent = current.find((item) => item.id === node.parentId);
      return { ...node, position: { x: Math.max(12, Math.min(Number(parent?.style?.width) - HOST_WIDTH - 12, node.position.x + dx)), y: Math.max(48, Math.min(Number(parent?.style?.height) - HOST_HEIGHT - 12, node.position.y + dy)) } };
    }));
    changed();
  }
  return <div className="min-w-0 space-y-3">
    <div className="flex flex-wrap gap-2" role="group" aria-label="Canvas controls">
      <Button size="sm" variant="secondary" aria-label="Fit view" disabled={!flow || saving} onClick={() => { void flow?.fitView({ padding: .15, duration: 0, maxZoom: 1 }); changed(); }}>Fit</Button>
      <Button size="sm" variant="secondary" aria-label="Auto layout" disabled={!flow || saving} onClick={() => { setNodes(topologyGraph(snapshot, onInspect, {}).nodes); setError(""); changed(); }}><span className="sm:hidden">Arrange</span><span className="hidden sm:inline">Auto layout</span></Button>
      <Button size="sm" variant="secondary" aria-label="Zoom in topology" disabled={!flow || saving} onClick={() => { void flow?.zoomIn({ duration: 0 }); changed(); }}><Plus size={16} /></Button>
      <Button size="sm" variant="secondary" aria-label="Zoom out topology" disabled={!flow || saving} onClick={() => { void flow?.zoomOut({ duration: 0 }); changed(); }}><Minus size={16} /></Button>
      {dirty && <Button size="sm" variant="secondary" disabled={saving} onClick={() => setDiscard(true)}>Discard changes</Button>}
    </div>
    <p className="hidden text-xs leading-5 text-muted sm:block">Drag a card by its header to arrange it. Lines show pool membership. Use List view to inspect nodes with a keyboard. Layout changes never move servers between pools.</p>
    {graph.adjusted > 0 && <p className="text-xs text-warning">Some saved positions were adjusted to fit the current pool inventory.</p>}
    <div className={`${styles.canvas} h-[min(65dvh,40rem)] min-h-96 overflow-hidden rounded-xl border border-border`} role="region" aria-label="Storage topology canvas">
      <ReactFlow<StorageFlowNode> nodes={rendered} edges={graph.edges} nodeTypes={nodeTypes}
        onInit={(instance) => { setFlow(instance); if (!Object.keys(snapshot.layout.positions).length) void instance.fitView({ padding: .15, maxZoom: 1 }); }}
        onNodesChange={(changes) => setNodes((current) => applyNodeChanges(changes, current))}
        onNodeDragStop={changed} onMoveEnd={(event) => { if (event) changed(); }}
        defaultViewport={snapshot.layout.viewport} minZoom={.1} maxZoom={4} nodesDraggable={!saving}
        nodesConnectable={false} nodesFocusable={false} edgesFocusable={false} edgesReconnectable={false}
        deleteKeyCode={null} panOnScroll zoomOnScroll={false} zoomOnPinch selectionOnDrag={false}
        onlyRenderVisibleElements preventScrolling aria-label="Pool membership map">
        <MiniMap pannable zoomable nodeColor="var(--border-strong)" maskColor="color-mix(in srgb, var(--background) 70%, transparent)" ariaLabel="Topology overview" />
      </ReactFlow>
    </div>
    <div className="flex flex-wrap items-end gap-2"><label className="min-w-0 flex-1 text-xs font-medium">Arrange with keyboard<select className="mt-1 min-h-10 w-full rounded-lg border border-border-strong bg-surface px-2 text-sm" value={arrange} disabled={saving} onChange={(event) => { setArrange(event.target.value); if (event.target.value) void flow?.fitView({ nodes: [{ id: event.target.value }], padding: .3, duration: 0, maxZoom: 1 }); }}><option value="">Choose a node</option>{snapshot.nodes.map((node) => <option key={node.id} value={node.id}>{node.hostname}</option>)}</select></label><div className="flex gap-1" role="group" aria-label="Move selected card">{[["left", -16, 0, ArrowLeft], ["up", 0, -16, ArrowUp], ["down", 0, 16, ArrowDown], ["right", 16, 0, ArrowRight]].map(([label, dx, dy, Icon]) => { const Direction = Icon as typeof ArrowLeft; return <Button key={label as string} size="sm" variant="secondary" aria-label={`Move card ${label}`} disabled={!arrange || saving} onClick={() => shift(dx as number, dy as number)}><Direction size={16} /></Button>; })}</div></div>
    <div className="flex flex-wrap items-end gap-3 border-t border-border pt-3"><label className="min-w-0 flex-1 text-xs font-medium">Save layout for<select className="mt-1 min-h-11 w-full rounded-xl border border-border-strong bg-surface px-3 text-sm" value={scope} disabled={saving} onChange={(event) => setScope(event.target.value as "personal" | "shared")}><option value="personal">Only me</option>{canConfigure && <option value="shared">Shared default</option>}</select></label><Button loading={saving} disabled={!dirty || !flow} onClick={() => void save()}>Save layout</Button></div>
    <p role="status" className="text-xs text-muted">{dirty ? "Unsaved layout changes" : `Saved ${scope} layout revision ${revisions[scope]}`}</p>
    {notice && <p role="status" className="text-sm text-success">{notice}</p>}
    {error && <p role="alert" className="text-sm text-danger">{error} Your current positions have been kept. Reload topology after resolving the conflict.</p>}
    <ConfirmDialog open={discard} title="Discard unsaved layout?" description="Return to the last saved layout in this view. Storage inventory will not change." confirmLabel="Discard layout changes" onClose={() => setDiscard(false)} onConfirm={() => { setNodes(topologyGraph(snapshot, onInspect, baseline.current.positions).nodes); void flow?.setViewport(baseline.current.viewport); setDirty(false); setError(""); setDiscard(false); }} />
  </div>;
}
