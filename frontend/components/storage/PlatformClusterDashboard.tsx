"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background, Controls, Handle, MarkerType, Position, ReactFlow,
  applyNodeChanges, type Edge, type Node, type NodeChange, type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import {
  Activity, AlertCircle, AlertTriangle, Check, Copy, Database, HardDrive,
  Layers3, Maximize2, Network, Plus, RefreshCw, RotateCcw,
  Server, ShieldCheck, X,
} from "lucide-react";
import Button from "@/components/ui/Button";
import { storageGet } from "@/lib/storage-control-service";
import styles from "./PlatformClusterDashboard.module.css";
import "@xyflow/react/dist/style.css";

type VolumeNode = {
  id: string; address: string; online: boolean; datacenter: string; rack: string;
  max_slots: number; free_slots: number; volumes: number; stored_bytes: number | null;
};
type DockerMetric = {
  docker_health: "healthy" | "unhealthy" | "starting" | "unknown";
  cpu_percent: number | null; memory_used_bytes: number | null; memory_limit_bytes: number | null;
  network_rx_bytes: number | null; network_tx_bytes: number | null;
  disk_total_bytes: number | null; disk_available_bytes: number | null;
};
type ResourceTelemetry = {
  state: "fresh" | "stale" | "invalid" | "not_collected";
  sampled_at: string | null; containers: Record<string, DockerMetric>;
};
type StorageAlert = { code: string; severity: "critical" | "warning"; title: string; detail: string };
type StorageCollection = { name: string; unique_volumes: number; volume_copies: number; stored_bytes: number };
type LiveState = {
  source: string; observed_at: string; master_online: boolean; s3_gateway_responding: boolean;
  nodes: VolumeNode[]; online_nodes: number; volume_slots: number; free_slots: number;
  used_volume_slots: number; stored_volume_bytes: number | null;
  physical_disk_bytes_available: null; error_code: string | null;
  routing_enabled: boolean; binding_ready: boolean; binding_revision: number | null;
  docker_metrics?: ResourceTelemetry; alerts?: StorageAlert[]; collections?: StorageCollection[];
};
type DeviceKind = "app" | "s3" | "filer" | "postgres" | "master" | "volume";
type DeviceStatus = "online" | "offline" | "responding" | "healthy" | "unhealthy" | "unmonitored" | "logical" | "stale";
type PacketData = Record<string, unknown> & {
  title: string; subtitle: string; kind: DeviceKind; status: DeviceStatus;
  volumeCount?: number; freeSlots?: number; maxSlots?: number;
};
type PacketNode = Node<PacketData, "packet">;

const LAYOUT_KEY = "bluedrive:platform-topology-layout:v3";
const fixedPositions: Record<string, { x: number; y: number }> = {
  application: { x: 30, y: 42 }, s3: { x: 235, y: 42 },
  filer: { x: 440, y: 42 }, postgres: { x: 645, y: 42 },
  master: { x: 440, y: 208 },
  volume: { x: 80, y: 380 }, volume2: { x: 315, y: 380 }, volume3: { x: 550, y: 380 },
};
const displayBytes = (bytes: number | null | undefined) => {
  if (bytes == null) return "Not monitored";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  const exponent = Math.min(4, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** exponent).toFixed(1)} ${units[exponent - 1]}`;
};
const percentUsed = (used: number | null | undefined, total: number | null | undefined) =>
  used != null && total != null && total > 0 ? `${(used / total * 100).toFixed(1)}%` : "Not monitored";
const statusText: Record<DeviceStatus, string> = {
  online: "Registered", offline: "Offline", responding: "Responding",
  healthy: "Docker healthy", unhealthy: "Docker unhealthy",
  unmonitored: "Not monitored", logical: "Logical link", stale: "Status unknown",
};

function defaultPosition(id: string): { x: number; y: number } {
  if (id in fixedPositions) return fixedPositions[id];
  const parsed = Number(id.replace(/^volume/, ""));
  const ordinal = Number.isFinite(parsed) ? parsed - 1 : 3;
  return { x: 80 + ((ordinal % 4) * 235), y: 380 + Math.floor(ordinal / 4) * 155 };
}

// Biểu tượng SVG là thành phần thật của node trong React Flow, không phải ảnh nền tĩnh.
function DeviceVisual({ kind }: { kind: DeviceKind }) {
  if (kind === "volume") return <svg viewBox="0 0 100 80" className={styles.hardware} aria-hidden="true">
    <rect x="23" y="7" width="54" height="67" rx="8" fill="#e9f0ff" stroke="#647fc3" strokeWidth="2" />
    {[17, 35, 53].map((top) => <g key={top}><rect x="30" y={top} width="40" height="13" rx="3" fill="#fff" stroke="#859ccd" /><circle cx="37" cy={top + 6.5} r="2.5" fill="#33aa83" /><rect x="46" y={top + 5} width="16" height="3" rx="1.5" fill="#becded" /></g>)}
  </svg>;
  if (kind === "master") return <svg viewBox="0 0 100 80" className={styles.hardware} aria-hidden="true">
    <path d="M12 34 24 21h57l9 13v26l-9 8H19l-7-8Z" fill="#e9eeff" stroke="#5b70ba" strokeWidth="2" />
    <rect x="19" y="37" width="62" height="22" rx="4" fill="#fff" stroke="#6c82c2" />
    {[27, 39, 51, 63].map((x) => <rect key={x} x={x} y="44" width="7" height="7" rx="1" fill="#788cc5" />)}
    <circle cx="75" cy="48" r="3" fill="#2cb787" />
  </svg>;
  const Icon = kind === "app" ? Network : kind === "s3" ? HardDrive : kind === "filer" ? Layers3 : Database;
  return <div className={styles.symbol}><Icon size={34} strokeWidth={1.6} aria-hidden="true" /></div>;
}

function PacketDevice({ data, selected }: NodeProps<PacketNode>) {
  return <div className={`${styles.packetNode} ${selected ? styles.selected : ""} ${styles[data.kind]}`}>
    <Handle type="target" id="left" position={Position.Left} className={styles.handle} />
    <Handle type="target" id="top" position={Position.Top} className={styles.handle} />
    <Handle type="source" id="right" position={Position.Right} className={styles.handle} />
    <Handle type="source" id="bottom" position={Position.Bottom} className={styles.handle} />
    <div className={styles.illustration}><DeviceVisual kind={data.kind} /></div>
    <div className={styles.deviceName} title={data.title}>{data.title}</div>
    <div className={`${styles.deviceState} ${styles[`status_${data.status}`]}`}>
      <span className={styles.statusDot} />{statusText[data.status]}
    </div>
    {data.kind === "volume" && <div className={styles.nodeVolumes}>
      {data.volumeCount ?? 0} volumes
    </div>}
  </div>;
}
const nodeTypes: NodeTypes = { packet: PacketDevice };

function LinkLine(source: string, target: string, sourceHandle: string, targetHandle: string, monitored: boolean): Edge {
  return {
    id: `${source}-${target}`, source, target, sourceHandle, targetHandle,
    type: "smoothstep", animated: monitored,
    style: { stroke: monitored ? "#6b81d8" : "#a6aec5", strokeWidth: 2, strokeDasharray: monitored ? undefined : "5 5" },
    markerEnd: { type: MarkerType.ArrowClosed, color: monitored ? "#6b81d8" : "#a6aec5", width: 15, height: 15 },
  };
}

function AddNodeGuide({ names, onClose, onRefresh }: { names: string[]; onClose: () => void; onRefresh: () => void }) {
  const [copied, setCopied] = useState(false);
  const next = Array.from({ length: 9 }, (_, index) => `volume${index + 4}`).find((name) => !names.includes(name));
  const script = next ? `& .\\infra\\seaweedfs\\add-platform-volume.ps1 -NodeName ${next} -Apply` : "";
  const copy = async () => {
    if (!script) return;
    try { await navigator.clipboard.writeText(script); setCopied(true); } catch { setCopied(false); }
  };
  return <div className={styles.dialogBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-label="Add storage node" className={styles.dialog}>
      <header className={styles.dialogHeader}>
        <h2 className="text-base font-semibold">Add storage node</h2>
        <button aria-label="Close" onClick={onClose} className={styles.iconButton}><X size={18} /></button>
      </header>
      <div className={styles.dialogBody}>
        <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-medium">Platform Docker</span><span className={styles.pill}>{next ? next : "Lab limit reached"}</span></div>
        {next ? <>
          <p className="text-xs text-muted">Run on the Platform host, then refresh to verify registration.</p>
          <div className={styles.commandBlock}>
            <code className="whitespace-pre-wrap break-all text-xs">{script}</code>
            <button type="button" onClick={copy} className={styles.copyButton} aria-label="Copy deployment command">{copied ? <Check size={15} /> : <Copy size={15} />}{copied ? "Copied" : "Copy"}</button>
          </div>
        </> : <p className="text-sm text-muted">No additional lab nodes are available.</p>}
      </div>
      <footer className="flex justify-end gap-2 border-t border-border p-3"><Button variant="secondary" size="sm" onClick={onClose}>Close</Button><Button size="sm" onClick={() => { onRefresh(); onClose(); }}><RefreshCw size={15} />Refresh nodes</Button></footer>
    </section>
  </div>;
}

export default function PlatformClusterDashboard() {
  const [snapshot, setSnapshot] = useState<LiveState | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [stale, setStale] = useState(false);
  const [selected, setSelected] = useState("volume");
  const [revision, setRevision] = useState(0);
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>(fixedPositions);
  const [showAdd, setShowAdd] = useState(false);
  const [logCommandCopied, setLogCommandCopied] = useState(false);
  const [instance, setInstance] = useState<{ fitView: (options?: { padding: number; duration: number }) => void } | null>(null);

  const restoreLayout = useCallback(() => {
  try {
    const saved = JSON.parse(
      localStorage.getItem(LAYOUT_KEY) ?? "null"
    ) as unknown;

    if (!saved || typeof saved !== "object" || Array.isArray(saved)) {
      return;
    }

    const accepted: Record<string, { x: number; y: number }> = {};

    for (const [key, value] of Object.entries(saved)) {
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        continue;
      }

      const point = value as Record<string, unknown>;

      if (
        typeof point.x !== "number" ||
        typeof point.y !== "number" ||
        !Number.isFinite(point.x) ||
        !Number.isFinite(point.y) ||
        Math.abs(point.x) > 10000 ||
        Math.abs(point.y) > 10000
      ) {
        continue;
      }

      accepted[key] = { x: point.x, y: point.y };
    }

    if (Object.keys(accepted).length > 0) {
      setPositions({ ...fixedPositions, ...accepted });
    }
  } catch {
    // Dữ liệu bố cục không hợp lệ: giữ vị trí mặc định.
  }
}, []);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const data = await storageGet<LiveState>({}, "platform/live/");
        if (active) { setSnapshot(data); setError(""); setStale(false); }
      } catch (cause) {
        if (active) { setStale(true); setError(cause instanceof Error ? cause.message : "Cannot read SeaweedFS topology."); }
      } finally { if (active) setLoading(false); }
    };
    void load();
    const timer = setInterval(() => { void load(); }, 10_000);
    return () => { active = false; clearInterval(timer); };
  }, [revision]);
  const refresh = useCallback(() => { setLoading(true); setRevision((value) => value + 1); }, []);
  const reset = useCallback(() => { setPositions(fixedPositions); localStorage.removeItem(LAYOUT_KEY); window.setTimeout(() => instance?.fitView({ padding: 0.2, duration: 300 }), 0); }, [instance]);

  const metricsFresh = !stale && snapshot?.docker_metrics?.state === "fresh";
  const dockerMetric = (name: string): DockerMetric | undefined =>
    metricsFresh ? snapshot?.docker_metrics?.containers[name] : undefined;
  const graphNodes = useMemo<PacketNode[]>(() => {
    const status = (good: boolean) => (stale || !snapshot) ? "stale" as const : good ? "online" as const : "offline" as const;
    const serviceState = (name: string): DeviceStatus => {
      const health = metricsFresh ? snapshot?.docker_metrics?.containers[name]?.docker_health : undefined;
      return health === "healthy" ? "healthy" : health === "unhealthy" ? "unhealthy" : "unmonitored";
    };
    const root: { id: string; title: string; subtitle: string; kind: DeviceKind; state: DeviceStatus }[] = [
      { id: "application", title: "BlueDrive", subtitle: "Application", kind: "app", state: "logical" },
      { id: "s3", title: "S3 Gateway", subtitle: "Port 8333", kind: "s3", state: (stale || !snapshot) ? "stale" : snapshot.s3_gateway_responding ? "responding" : "offline" },
      { id: "filer", title: "Filer", subtitle: "Metadata API", kind: "filer", state: serviceState("filer") },
      { id: "postgres", title: "PostgreSQL", subtitle: "Filer metadata", kind: "postgres", state: serviceState("postgres") },
      { id: "master", title: "SeaweedFS Master", subtitle: "Port 9333", kind: "master", state: status(Boolean(snapshot?.master_online)) },
    ];
    const nodes: PacketNode[] = root.map(({ id, title, subtitle, kind, state }) => ({
      id, type: "packet", position: positions[id] ?? defaultPosition(id),
      data: { title, subtitle, kind, status: state },
    }));
    for (const item of snapshot?.nodes ?? []) {
      nodes.push({ id: item.id, type: "packet", position: positions[item.id] ?? defaultPosition(item.id),
        data: { title: item.id.toUpperCase(), subtitle: item.address || "No registration", kind: "volume", status: status(item.online),
          volumeCount: item.volumes, freeSlots: item.free_slots, maxSlots: item.max_slots },
      });
    }
    return nodes;
  }, [snapshot, positions, stale, metricsFresh]);

  const graphEdges = useMemo<Edge[]>(() => [
    LinkLine("application", "s3", "right", "left", false),
    LinkLine("s3", "filer", "right", "left", false),
    LinkLine("filer", "postgres", "right", "left", false),
    LinkLine("filer", "master", "bottom", "top", false),
    ...(snapshot?.nodes ?? []).map((node) => LinkLine("master", node.id, "bottom", "top", Boolean(snapshot?.master_online && node.online && !stale))),
  ], [snapshot, stale]);
  const changeNodes = useCallback((changes: NodeChange<PacketNode>[]) => {
    if (!changes.some((change) => change.type === "position")) return;
    const changed = applyNodeChanges(changes, graphNodes);
    setPositions((current) => {
      const next = { ...current };
      for (const item of changed) if (item.position) next[item.id] = item.position;
      return next;
    });
  }, [graphNodes]);
  const inspectedVolume = snapshot?.nodes.find((node) => node.id === selected);
  const inspectedMetrics = dockerMetric(selected);
  const diagnosticCommand = /^(?:master|filer|s3|postgres|volume(?:[2-9]|1[0-2])?)$/.test(selected)
    ? `docker logs --tail 100 bluedrive-seaweedfs-${selected}-1` : null;
  const inspected = graphNodes.find((node) => node.id === selected);
  const online = snapshot?.online_nodes ?? 0;
  const total = snapshot?.nodes.length ?? 0;
  const routingReady = Boolean(!stale && snapshot?.binding_ready && snapshot?.routing_enabled);
  const alerts = stale ? [] : (snapshot?.alerts ?? []);
  const live = !stale && !error && snapshot?.master_online;
  const date = snapshot?.observed_at && !Number.isNaN(Date.parse(snapshot.observed_at)) ? new Date(snapshot.observed_at).toLocaleString() : "Not available";

  return <main className={styles.dashboard}>
    <header className={styles.pageHeader}>
      <div><h1 className="text-2xl font-semibold">Platform storage</h1></div>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" onClick={refresh} disabled={loading}><RefreshCw size={16} />Refresh</Button>
        <Button size="sm" onClick={() => setShowAdd(true)}><Plus size={16} />Add Node</Button>
      </div>
    </header>
    <div className={styles.clusterBanner}>
      <span className={styles.clusterTitle}><Network size={18} />SeaweedFS Platform</span>
      <div className={styles.bannerBadges}>
        <span className={`${styles.pill} ${live ? styles.good : stale || !snapshot ? styles.neutral : styles.bad}`}><span className={styles.statusDot} />{live ? "Master online" : stale || !snapshot ? "Master unknown" : "Master offline"}</span>
        <span className={`${styles.pill} ${routingReady ? styles.good : styles.neutral}`}><ShieldCheck size={13} />{routingReady ? `Routing · r${snapshot?.binding_revision}` : stale || !snapshot ? "Routing unknown" : "Routing unavailable"}</span>
      </div>
    </div>
    {error && <p role="alert" className="rounded-xl border border-danger/30 bg-surface p-3 text-sm text-danger">Topology unavailable. {error}</p>}
    <section className={styles.metrics} aria-label="Storage metrics">
      <div className={styles.metric}><div className={styles.metricHeading}><Server size={16} />Nodes</div><p className={styles.metricValue}>{snapshot && !stale ? `${online} / ${total}` : "—"}</p></div>
      <div className={styles.metric}><div className={styles.metricHeading}><Layers3 size={16} />Volumes</div><p className={styles.metricValue}>{snapshot && !stale ? snapshot.used_volume_slots : "—"}</p><p className={styles.metricExtra}>{snapshot && !stale ? `${snapshot.free_slots} free slots` : ""}</p></div>
      <div className={styles.metric}><div className={styles.metricHeading}><HardDrive size={16} />Volume data</div><p className={styles.metricValue}>{displayBytes(stale ? null : snapshot?.stored_volume_bytes)}</p></div>
      <div className={styles.metric}><div className={styles.metricHeading}><Activity size={16} />S3 Gateway</div><p className={styles.metricValue}>{!snapshot ? "—" : stale ? "Unknown" : snapshot.s3_gateway_responding ? "Responding" : "Offline"}</p></div>
    </section>
    <section className={styles.operations} aria-label="Platform health and alerts">
      <div className={styles.compactHealthHead}>
        <div className="flex flex-wrap items-center gap-3"><h2 className="font-semibold">Operational health</h2>
          <span className={`${styles.pill} ${alerts.length ? styles.bad : stale || !snapshot || !metricsFresh ? styles.neutral : styles.good}`}>
            {alerts.length ? `${alerts.length} alert${alerts.length === 1 ? "" : "s"}` : stale || !snapshot ? "Unknown" : "No active alerts"}
          </span>
        </div>
        <span className={styles.telemetryChip} title={snapshot?.docker_metrics?.sampled_at ? `Sample: ${snapshot.docker_metrics.sampled_at}` : "No Docker metrics sample"}>
          Docker metrics: {metricsFresh ? "Live sample" : snapshot?.docker_metrics?.state === "stale" ? "Stale" : "Not monitored"}
        </span>
      </div>
      {alerts.length > 0 && <div className={styles.alertGrid}>{alerts.map((alert) => <div key={`${alert.code}-${alert.title}`} role="alert" className={`${styles.alertItem} ${alert.severity === "critical" ? styles.alertCritical : styles.alertWarning}`}>
        {alert.severity === "critical" ? <AlertCircle size={17} /> : <AlertTriangle size={17} />}<div><strong>{alert.title}</strong><p>{alert.detail}</p></div>
      </div>)}</div>}
    </section>
    <section className={styles.workArea}>
      <div className={styles.mapPanel}>
        <div className={styles.mapHead}><h2 className="font-semibold">Cluster topology</h2><div className="flex gap-1"><button title="Fit map" aria-label="Fit map" onClick={() => instance?.fitView({ padding: 0.18, duration: 250 })} className={styles.iconButton}><Maximize2 size={17} /></button><button title="Reset layout" aria-label="Reset layout" onClick={reset} className={styles.iconButton}><RotateCcw size={17} /></button></div></div>
        <div className={styles.topology} role="region" aria-label="Platform storage node topology">
          <ReactFlow<PacketNode, Edge> className={styles.flow} nodes={graphNodes} edges={graphEdges} nodeTypes={nodeTypes}
            onNodesChange={changeNodes} onNodeDragStop={(_, node) => { const next = { ...positions, [node.id]: node.position }; setPositions(next); localStorage.setItem(LAYOUT_KEY, JSON.stringify(next)); }} onNodeClick={(_, node) => setSelected(node.id)}
            onInit={(value) => {setInstance(value); restoreLayout();}} nodesConnectable={false} edgesReconnectable={false} elementsSelectable
            fitView fitViewOptions={{ padding: 0.18 }} minZoom={0.35} maxZoom={1.8} proOptions={{ hideAttribution: false }}>
            <Background gap={24} size={1.5} /><Controls showInteractive={false} position="bottom-left" />
          </ReactFlow>
        </div>
        <div className={styles.mapFooter}><span><span className={styles.legendDot} />Online</span><span><span className={`${styles.legendDot} ${styles.redDot}`} />Offline</span><span><span className={`${styles.legendDot} ${styles.grayDot}`} />Unknown</span><time className="ml-auto" title={date}>Updated {date}</time></div>
      </div>
      <aside className={styles.inspector} aria-label="Storage node details"><div className={styles.inspectorHead}><h2 className="font-semibold">Device details</h2></div>
        {inspected ? <div className="space-y-4 p-4"><div className="flex items-center gap-3"><div className={styles.inspectorIllustration}><DeviceVisual kind={inspected.data.kind} /></div><div className="min-w-0"><p className="font-semibold">{inspected.data.title}</p><p className="text-xs text-muted">{inspected.data.subtitle}</p></div></div><span className={`${styles.pill} ${inspected.data.status === "online" || inspected.data.status === "responding" || inspected.data.status === "healthy" ? styles.good : inspected.data.status === "unhealthy" || inspected.data.status === "offline" ? styles.bad : styles.neutral}`}><span className={styles.statusDot} />{statusText[inspected.data.status]}</span>
          {inspectedVolume ? <>
            <dl className={styles.details}>
              <dt>Address</dt><dd className="break-all">{inspectedVolume.address || "Not registered"}</dd>
              <dt>Volumes</dt><dd>{inspectedVolume.volumes}</dd>
              <dt>Free slots</dt><dd>{inspectedVolume.free_slots} / {inspectedVolume.max_slots}</dd>
              <dt>CPU</dt><dd>{inspectedMetrics?.cpu_percent == null ? "Not monitored" : `${inspectedMetrics.cpu_percent.toFixed(2)}%`}</dd>
              <dt>Memory</dt><dd>{displayBytes(inspectedMetrics?.memory_used_bytes)} ({percentUsed(inspectedMetrics?.memory_used_bytes, inspectedMetrics?.memory_limit_bytes)})</dd>
              <dt>/data free</dt><dd>{displayBytes(inspectedMetrics?.disk_available_bytes)}</dd>
            </dl>
            <details className={styles.moreDetails}><summary>More details</summary>
              <dl className={styles.details}>
                <dt>Datacenter</dt><dd>{inspectedVolume.datacenter || "—"}</dd>
                <dt>Rack</dt><dd>{inspectedVolume.rack || "—"}</dd>
                <dt>Volume bytes</dt><dd>{displayBytes(inspectedVolume.stored_bytes)}</dd>
                <dt>Disk total</dt><dd>{displayBytes(inspectedMetrics?.disk_total_bytes)}</dd>
                <dt>Network Rx / Tx</dt><dd>{displayBytes(inspectedMetrics?.network_rx_bytes)} / {displayBytes(inspectedMetrics?.network_tx_bytes)}</dd>
                <dt>Docker health</dt><dd>{inspectedMetrics?.docker_health ?? "Not monitored"}</dd>
              </dl>
            </details>
          </> : <dl className={styles.details}>
            <dt>Docker health</dt><dd>{inspectedMetrics?.docker_health ?? "Not monitored"}</dd>
            <dt>CPU</dt><dd>{inspectedMetrics?.cpu_percent == null ? "Not monitored" : `${inspectedMetrics.cpu_percent.toFixed(2)}%`}</dd>
            <dt>Memory</dt><dd>{displayBytes(inspectedMetrics?.memory_used_bytes)}</dd>
            <dt>Network Rx / Tx</dt><dd>{displayBytes(inspectedMetrics?.network_rx_bytes)} / {displayBytes(inspectedMetrics?.network_tx_bytes)}</dd>
          </dl>}
          {diagnosticCommand && <button type="button" className={styles.diagnosticButton} onClick={async () => { try { await navigator.clipboard.writeText(diagnosticCommand); setLogCommandCopied(true); } catch { setLogCommandCopied(false); } }}><Copy size={14} />{logCommandCopied ? "Copied" : "Copy log command"}</button>}
        </div> : <p className="p-4 text-sm text-muted">Select a device on the map to inspect it.</p>}
      </aside>
    </section>
    <details className={styles.inventory}><summary className={styles.foldHead}><h2 className="font-semibold">Volume node inventory</h2><span className={styles.sectionMeta}>{total} nodes</span></summary><div className="overflow-x-auto"><table className={styles.nodeTable}><thead><tr><th>Node</th><th>Status</th><th>Address</th><th>Volumes</th><th>Free slots</th><th>Stored bytes</th><th>CPU</th><th>RAM used</th><th>Docker health</th></tr></thead><tbody>{(snapshot?.nodes ?? []).map((item) => <tr key={item.id} onClick={() => setSelected(item.id)} className={selected === item.id ? styles.activeRow : ""}><td className="font-semibold">{item.id}</td><td><span className={item.online && !stale ? "text-success" : "text-muted"}>{stale ? "Unknown" : item.online ? "Registered" : "Offline"}</span></td><td>{item.address || "—"}</td><td>{item.volumes}</td><td>{item.free_slots}/{item.max_slots}</td><td>{displayBytes(item.stored_bytes)}</td><td>{dockerMetric(item.id)?.cpu_percent == null ? "—" : `${dockerMetric(item.id)!.cpu_percent!.toFixed(2)}%`}</td><td>{displayBytes(dockerMetric(item.id)?.memory_used_bytes)}</td><td>{dockerMetric(item.id)?.docker_health ?? "Not monitored"}</td></tr>)}</tbody></table></div></details>
    <details className={styles.inventory} aria-label="Storage collections"><summary className={styles.foldHead}><h2 className="font-semibold">Collection inventory</h2><span className={styles.sectionMeta}>{snapshot?.collections?.length ?? 0} collections</span></summary>
      <div className="overflow-x-auto"><table className={styles.nodeTable}><thead><tr><th>Collection</th><th>Unique volume IDs</th><th>Volume copies</th><th>Reported volume bytes</th></tr></thead><tbody>
        {(snapshot?.collections ?? []).map((item) => <tr key={item.name}><td className="font-semibold">{item.name || "(default)"}</td><td>{item.unique_volumes}</td><td>{item.volume_copies}</td><td>{displayBytes(item.stored_bytes)}</td></tr>)}
        {!snapshot?.collections?.length && <tr><td colSpan={4}>No volume inventory available.</td></tr>}
      </tbody></table></div>
    </details>
    <details className={styles.notes}><summary>Metric definitions</summary><p>Volume data is SeaweedFS-reported bytes, not physical disk usage. Docker metrics require a current host collector sample. Docker Desktop nodes may share one physical disk; do not sum filesystem capacity. Dragging a node only changes the diagram.</p></details>
    {showAdd && <AddNodeGuide names={(snapshot?.nodes ?? []).map((node) => node.id)} onClose={() => setShowAdd(false)} onRefresh={refresh} />}
  </main>;
}
