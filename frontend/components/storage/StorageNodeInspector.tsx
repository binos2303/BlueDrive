"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { X } from "lucide-react";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";
import AdminSegmentTabs from "@/components/admin/AdminSegmentTabs";
import { storageGet, type StorageDisk, type StorageHost, type StoragePage, type StorageTelemetry } from "@/lib/storage-control-service";
import { nodeTelemetryHealth } from "./telemetry-model";

const media = "(min-width: 1024px)";
function subscribe(callback: () => void) { const match = window.matchMedia(media); match.addEventListener("change", callback); return () => match.removeEventListener("change", callback); }
function capacity(value: number | null) { if (value === null) return "Not reported"; return `${(value / 1024 ** 3).toLocaleString(undefined, { maximumFractionDigits: 1 })} GiB`; }
type EventRow = { id: string; action: string; created_at: string; reason: string };

export default function StorageNodeInspector({ node, telemetry, tenantId, onClose }: { node: StorageHost; telemetry?: StorageTelemetry | null; tenantId?: string; onClose: () => void }) {
  const wide = useSyncExternalStore(subscribe, () => window.matchMedia(media).matches, () => false);
  const [tab, setTab] = useState<"overview" | "disks" | "events">("overview");
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [details, setDetails] = useState<StorageHost | null>(null);
  const [rows, setRows] = useState<StoragePage<StorageDisk | EventRow> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    const base = `clusters/${node.cluster_id}/`;
    async function load() {
      setLoading(true);
      try {
        if (tab === "overview") {
          const result = await storageGet<StorageHost>({ tenantId }, base + `nodes/${node.id}/`, controller.signal);
          if (!controller.signal.aborted) { setDetails(result); setError(""); }
        } else {
          const result = await storageGet<StoragePage<StorageDisk | EventRow>>({ tenantId }, base + `${tab}/?node_id=${node.id}&page=${page}&page_size=20`, controller.signal);
          if (!controller.signal.aborted) { setRows(result); setError(""); }
        }
      } catch (cause) { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not refresh node details."); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void load();
    return () => controller.abort();
  }, [node.id, node.cluster_id, tenantId, tab, page, retry]);
  const inventory = details ?? node;
  const current = telemetry ? { ...inventory, health: nodeTelemetryHealth(telemetry,node.id) } : inventory;
  const metrics = telemetry?.nodes[node.id]?.metrics;
  const content = <div className="space-y-4">
    <AdminSegmentTabs label="Node detail sections" value={tab} onChange={(value) => { setTab(value); setPage(1); setRows(null); }} tabs={[{ value: "overview", label: "Overview" }, { value: "disks", label: "Disks" }, { value: "events", label: "Events" }]} />
    {loading && <p role="status" className="text-sm text-muted">Refreshing node details…</p>}
    {error && <div className="space-y-2"><p role="alert" className="text-sm text-danger">{error} Displayed inventory may be stale.</p><Button size="sm" variant="secondary" onClick={() => setRetry(retry + 1)}>Retry node details</Button></div>}
    {tab === "overview" && <><dl className="space-y-3 text-sm">{[
      ["Hostname", current.hostname], ["Node ID", current.id], ["IP addresses", current.private_ips.join(", ") || "Not reported"],
      ["Agent identity", current.agent_identity ?? "Not enrolled"], ["Inventory", current.inventory_status],
      ["Health", current.health.status], ["Status source", current.health.source],
      ["Observed at", current.health.observed_at ? new Date(current.health.observed_at).toLocaleString() : "No observation"],
      ["Last successful sample", current.health.last_success_at ? new Date(current.health.last_success_at).toLocaleString() : "No sample"],
      ["Last seen in inventory", current.last_seen ? new Date(current.last_seen).toLocaleString() : "Not reported"],
    ].map(([label, value]) => <div key={label}><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 wrap-anywhere">{value}</dd></div>)}</dl>{metrics ? <div className="border-t border-border pt-3"><p className="mb-2 text-xs text-muted">{current.health.stale ? "Last known metrics · Stale" : "Current node metrics"}</p><dl className="space-y-2 text-sm">{[["CPU", metrics.node_cpu_percent === undefined ? "Not reported" : `${metrics.node_cpu_percent.toFixed(1)}%`], ["RAM used", metrics.node_ram_percent === undefined ? "Not reported" : `${metrics.node_ram_percent.toFixed(1)}%`], ["Process uptime", metrics.node_uptime_seconds === undefined ? "Not reported" : `${metrics.node_uptime_seconds.toLocaleString()} seconds`], ["Filesystem free", capacity(metrics.node_filesystem_free_bytes ?? null)], ["Network receive", metrics.node_network_rx_bytes_per_second === undefined ? "Not reported" : `${metrics.node_network_rx_bytes_per_second.toLocaleString()} bytes/s`], ["Network transmit", metrics.node_network_tx_bytes_per_second === undefined ? "Not reported" : `${metrics.node_network_tx_bytes_per_second.toLocaleString()} bytes/s`]].map(([label,value]) => <div key={label}><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 tabular-nums">{value}</dd></div>)}</dl></div> : <p className="border-t border-border pt-3 text-xs leading-5 text-muted">CPU, RAM, process uptime and live disk health are not collected. Registration and last-seen inventory do not confirm that a server is online.</p>}</>}
    {tab !== "overview" && !loading && !error && !rows?.results.length && <p className="text-sm text-muted">{tab === "disks" ? "No disks recorded for this node." : "No node events recorded."}</p>}
    {tab === "disks" && rows && <ul className="divide-y divide-border">{rows.results.map((record) => { const disk = record as StorageDisk; return <li key={disk.id} className="space-y-1 py-3 text-sm"><p className="wrap-anywhere font-medium">{disk.stable_disk_id}</p><p className="wrap-anywhere text-xs text-muted">{disk.mount_path}</p><p className="text-xs">Declared capacity: {capacity(disk.capacity_bytes)}</p><p className="text-xs text-muted">Source: inventory · Health: {disk.health.status}</p></li>; })}</ul>}
    {tab === "events" && rows && <ul className="divide-y divide-border">{rows.results.map((record) => { const event = record as EventRow; return <li key={event.id} className="space-y-1 py-3 text-sm"><p className="wrap-anywhere font-medium">{event.action}</p><p className="wrap-anywhere text-xs text-muted">{event.reason}</p><p className="text-xs text-muted">{new Date(event.created_at).toLocaleString()}</p></li>; })}</ul>}
    {tab !== "overview" && rows && (page > 1 || rows.has_more) && <div className="flex flex-wrap items-center gap-2"><Button size="sm" variant="secondary" disabled={loading || page === 1} onClick={() => setPage(page - 1)}>Previous details</Button><span className="text-xs text-muted">Page {page}</span><Button size="sm" variant="secondary" disabled={loading || !rows.has_more} onClick={() => setPage(page + 1)}>Next details</Button></div>}
  </div>;
  if (!wide) return <Dialog open title={node.hostname} description="Recorded node details" onClose={onClose}>{content}</Dialog>;
  return <aside aria-label={`Node inspector: ${node.hostname}`} className="min-w-0 border-t border-border bg-surface p-4 lg:border-l lg:border-t-0"><div className="mb-3 flex items-start justify-between gap-3"><h3 className="min-w-0 wrap-anywhere font-semibold">{node.hostname}</h3><Button size="sm" variant="ghost" aria-label="Close node inspector" onClick={onClose}><X size={18} /></Button></div>{content}</aside>;
}
