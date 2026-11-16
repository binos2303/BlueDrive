"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";
import Button from "@/components/ui/Button";
import AdminSegmentTabs from "@/components/admin/AdminSegmentTabs";
import { AccountServiceError } from "@/lib/account-service";
import { storageGet, type StorageHost, type StoragePage, type StorageTopologySnapshot } from "@/lib/storage-control-service";
import { matchesHost } from "./topology-model";
import StorageNodeInspector from "./StorageNodeInspector";
import StorageMonitoring from "./StorageMonitoring";
import useStorageTelemetry from "./useStorageTelemetry";
import { nodeTelemetryHealth } from "./telemetry-model";

const Canvas = dynamic(() => import("./TopologyCanvas"), { ssr: false, loading: () => <p role="status" className="p-6 text-sm text-muted">Loading topology canvas…</p> });
const field = "mt-1 min-h-11 w-full rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground";

export default function StorageTopology({ clusterId, tenantId, canConfigure, monitoringEnabled = false, onDirtyChange }: { clusterId: string; tenantId?: string; canConfigure: boolean; monitoringEnabled?: boolean; onDirtyChange: (dirty: boolean) => void }) {
  const monitoring = useStorageTelemetry(clusterId, tenantId, monitoringEnabled);
  const [snapshot, setSnapshot] = useState<StorageTopologySnapshot | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [view, setView] = useState<"canvas" | "list">("canvas");
  const [query, setQuery] = useState("");
  const [pool, setPool] = useState("all");
  const [status, setStatus] = useState("all");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [selected, setSelected] = useState<StorageHost | null>(null);
  const [tooLarge, setTooLarge] = useState(false);
  const [page, setPage] = useState(1);
  const [paged, setPaged] = useState<StoragePage<StorageHost> | null>(null);
  const [listLoading, setListLoading] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setLoading(true);
      try {
        const result = await storageGet<StorageTopologySnapshot>({ tenantId }, `clusters/${clusterId}/topology/`, controller.signal);
        if (!controller.signal.aborted) { setSnapshot(result); setError(""); setTooLarge(false); }
      } catch (cause) {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "Could not load topology.");
          if (cause instanceof AccountServiceError && cause.status === 422) { setTooLarge(true); setView("list"); setError(""); }
        }
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void load();
    return () => controller.abort();
  }, [clusterId, tenantId, retry]);
  useEffect(() => {
    if (!tooLarge) return;
    const controller = new AbortController();
    async function load() {
      setListLoading(true);
      try {
        const result = await storageGet<StoragePage<StorageHost>>({ tenantId }, `clusters/${clusterId}/nodes/?page=${page}&q=${encodeURIComponent(query)}`, controller.signal);
        if (!controller.signal.aborted) setPaged(result);
      } catch (cause) { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not load node list."); }
      finally { if (!controller.signal.aborted) setListLoading(false); }
    }
    void load();
    return () => controller.abort();
  }, [tooLarge, clusterId, tenantId, page, query, retry]);
  const inspect = useCallback((id: string) => { const node = snapshot?.nodes.find((item) => item.id === id); if (node) setSelected(node); }, [snapshot]);
  const changeDirty = useCallback((value: boolean) => { setDirty(value); onDirtyChange(value); }, [onDirtyChange]);
  const filtered = useMemo(() => snapshot?.nodes.filter((node) => matchesHost(node, query, pool, status)) ?? [], [snapshot, query, pool, status]);
  const ids = useMemo(() => new Set(filtered.map((node) => node.id)), [filtered]);
  const rows = tooLarge ? paged?.results ?? [] : filtered;
  return <section className="overflow-hidden rounded-2xl border border-border bg-surface" aria-label="Storage topology">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4"><div><h2 className="font-semibold">Topology</h2><p className="mt-1 text-xs text-muted">{monitoringEnabled ? "Recorded pools, nodes and disks" : `Recorded inventory · Health ${snapshot?.health.status ?? "unknown"} · Source: ${snapshot?.health.source ?? "not_collected"}`}</p></div><Button variant="secondary" size="sm" disabled={dirty || loading} onClick={() => { setPaged(null); setRetry(retry + 1); }}>Reload topology</Button></div>
    {loading && <p role="status" className="p-4 text-sm text-muted">Refreshing storage inventory…</p>}
    {monitoringEnabled && <StorageMonitoring {...monitoring} tenantId={tenantId} />}
    {error && <p role="alert" className="px-4 pt-4 text-sm text-danger">{error}{snapshot ? " Displayed inventory may be stale." : " Retry loading or use the available node list."}</p>}
    {tooLarge && <p role="status" className="px-4 pt-4 text-sm text-muted">This inventory exceeds the canvas limit. Use the paginated node list to inspect all recorded nodes.</p>}
    {listLoading && <p role="status" className="px-4 pt-4 text-sm text-muted">Loading node list…</p>}
    <div className="space-y-4 p-4">
      <AdminSegmentTabs label="Topology views" value={view} onChange={setView} tabs={[...(!tooLarge ? [{ value: "canvas" as const, label: "Canvas" }] : []), { value: "list", label: "List view" }]} />
      <Button variant="secondary" size="sm" className="sm:hidden" aria-expanded={filtersOpen} aria-controls="topology-filters" onClick={() => setFiltersOpen(!filtersOpen)}>Filters{query || pool !== "all" || status !== "all" ? " · Active" : ""}</Button>
      <div id="topology-filters" className={`${filtersOpen ? "grid" : "hidden sm:grid"} gap-3 sm:grid-cols-3`}><label className="text-xs font-medium">Find nodes<input className={field} placeholder="Name, IP or node ID" value={query} maxLength={100} onChange={(event) => { setQuery(event.target.value); setPage(1); }} /></label>{!tooLarge && <><label className="text-xs font-medium">Pool<select className={field} value={pool} onChange={(event) => setPool(event.target.value)}><option value="all">All pools</option><option value="unassigned">Unassigned</option>{snapshot?.pools.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="text-xs font-medium">Inventory state<select className={field} value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All states</option>{[...new Set(snapshot?.nodes.map((node) => node.inventory_status))].map((value) => <option key={value} value={value}>{value}</option>)}</select></label></>}</div>
      {snapshot && !snapshot.nodes.length && !loading && <div className="py-6"><h3 className="text-sm font-semibold">No node inventory recorded</h3><p className="mt-2 max-w-prose text-sm leading-6 text-muted">Connecting an S3 bucket does not discover physical servers or disks. Nodes will appear after an approved inventory source registers them.</p></div>}
      {!!snapshot?.nodes.length && !filtered.length && <p role="status" className="text-sm text-muted">No nodes match these filters.</p>}
      <div className={`grid min-w-0 ${selected ? "lg:grid-cols-[minmax(0,1fr)_18rem]" : "grid-cols-1"}`}>
        <div className="min-w-0">
          {snapshot && snapshot.nodes.length > 0 && <div hidden={view !== "canvas"} className={selected ? "lg:pr-4" : ""}><Canvas key={`${snapshot.cluster_id}:${retry}`} snapshot={snapshot} telemetry={monitoring.data} tenantId={tenantId} canConfigure={canConfigure} onInspect={inspect} onDirtyChange={changeDirty} queryIds={ids} /></div>}
          {view === "list" && <div className={selected ? "lg:pr-4" : ""}><ul className="divide-y divide-border" aria-label="Storage node list">{rows.map((node) => <li key={node.id} className="flex flex-wrap items-center justify-between gap-3 py-3"><div className="min-w-0"><p className="wrap-anywhere text-sm font-semibold">{node.hostname}</p><p className="mt-1 wrap-anywhere text-xs text-muted">{node.private_ips.join(", ") || "IP not reported"} · Health: {monitoring.data ? nodeTelemetryHealth(monitoring.data,node.id).status : node.health.status} · {node.inventory_status}</p></div><Button size="sm" variant="secondary" aria-label={`Inspect ${node.hostname}`} onClick={() => setSelected(node)}>Inspect</Button></li>)}</ul>{tooLarge && paged && <div className="mt-4 flex flex-wrap items-center gap-3"><Button variant="secondary" size="sm" disabled={page === 1} onClick={() => { setPaged(null); setPage(page - 1); }}>Previous nodes</Button><span className="text-xs text-muted">Page {page} · {paged.count} nodes</span><Button variant="secondary" size="sm" disabled={!paged.has_more} onClick={() => { setPaged(null); setPage(page + 1); }}>Next nodes</Button></div>}</div>}
        </div>
        {selected && <StorageNodeInspector key={selected.id} node={selected} telemetry={monitoring.data} tenantId={tenantId} onClose={() => setSelected(null)} />}
      </div>
    </div>
  </section>;
}
