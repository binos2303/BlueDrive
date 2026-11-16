"use client";

import { useState, type FormEvent } from "react";
import Button from "@/components/ui/Button";
import { storageWrite, type StorageAlert, type StorageTelemetry } from "@/lib/storage-control-service";

const labels: Record<string,string> = { read_quorum_lost:"Read quorum lost", write_quorum_lost:"Write quorum lost", disk_failures:"Disk failures detected", nodes_unavailable:"Nodes reported unavailable", collector_unavailable:"Collector unavailable", telemetry_stale:"Monitoring samples are stale", capacity_warning:"Storage capacity warning", capacity_critical:"Storage capacity critical" };
function metric(value: number | undefined, bytes = false) { return value === undefined ? "Not reported" : bytes ? `${(value / 1024 ** 3).toLocaleString(undefined, { maximumFractionDigits: 1 })} GiB` : value.toLocaleString(); }

export default function StorageMonitoring({ data, error, mode, refresh, tenantId }: { data: StorageTelemetry | null; error: string; mode: string; refresh: () => void; tenantId?: string }) {
  const [selected, setSelected] = useState<StorageAlert | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  async function acknowledge(event: FormEvent) {
    event.preventDefault();
    if (!selected || !data || saving) return;
    setSaving(true); setSaveError("");
    try {
      await storageWrite({ tenantId }, `clusters/${data.cluster_id}/alerts/${selected.id}/acknowledge/`, { expected_revision: selected.revision, reason: reason.trim() });
      setSelected(null); setReason(""); refresh();
    } catch (cause) { setSaveError(cause instanceof Error ? cause.message : "Could not acknowledge this alert. Refresh and retry."); }
    finally { setSaving(false); }
  }
  const health = data?.health;
  return <div aria-label="Storage monitoring" className="space-y-3 border-b border-border p-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-sm font-semibold">Monitoring: <span className={health?.status === "critical" ? "text-danger" : health?.status === "healthy" ? "text-success" : "text-muted"}>{health?.status ?? "unknown"}{health?.stale ? " · Stale" : ""}</span></h3><p className="mt-1 text-xs text-muted">{mode}</p></div><Button size="sm" variant="secondary" onClick={refresh}>Refresh monitoring</Button></div>
    {error && <p role="alert" className="max-w-prose text-sm text-danger">{error}</p>}
    {data && !data.configured && <p className="max-w-prose text-sm text-muted">Monitoring has not been configured for this storage. Inventory alone does not confirm that servers are online.</p>}
    {data?.configured && <><p className="wrap-anywhere text-xs leading-5 text-muted">{health?.stale ? "Last known values" : "Current samples"} · Observed: {health?.observed_at ? new Date(health.observed_at).toLocaleString() : "No observation"} · Source: {health?.source}</p><dl className="grid grid-cols-2 gap-x-5 gap-y-3 text-sm sm:grid-cols-4">{[
      ["Read quorum", data.cluster_metrics.cluster_read_ready === undefined ? "Not reported" : data.cluster_metrics.cluster_read_ready ? "Ready" : "Unavailable"],
      ["Write quorum", data.cluster_metrics.cluster_write_ready === undefined ? "Not reported" : data.cluster_metrics.cluster_write_ready ? "Ready" : "Unavailable"],
      ["Failed disks", metric(data.cluster_metrics.cluster_failed_disks)], ["Nodes unavailable", metric(data.cluster_metrics.cluster_offline_nodes)],
      ["Raw capacity", metric(data.cluster_metrics.raw_capacity_bytes,true)], ["Usable capacity", metric(data.cluster_metrics.usable_capacity_bytes,true)],
      ["Usable free", metric(data.cluster_metrics.usable_free_bytes,true)], ["Logical data", metric(data.cluster_metrics.logical_used_bytes,true)],
    ].map(([label,value]) => <div key={label}><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 tabular-nums">{value}</dd></div>)}</dl></>}
    {!!data?.alerts.length && <div className="border-t border-border pt-3"><h4 className="text-sm font-medium">Active alerts ({data.alerts.length})</h4><ul className="mt-1 divide-y divide-border">{data.alerts.map((alert) => <li key={alert.id} className="flex flex-wrap items-center justify-between gap-2 py-2"><div><p className={`text-sm ${alert.severity === "critical" ? "text-danger" : "text-foreground"}`}>{labels[alert.code] ?? "Storage incident"} · {alert.severity}</p><p className="mt-1 text-xs text-muted">Since {new Date(alert.first_seen_at).toLocaleString()}{alert.acknowledged_at ? " · Acknowledged" : ""}</p></div>{!alert.acknowledged_at && <Button size="sm" variant="secondary" onClick={() => { setSelected(alert); setSaveError(""); }}>Acknowledge {labels[alert.code]?.toLowerCase() ?? "alert"}</Button>}</li>)}</ul></div>}
    {selected && <form onSubmit={(event) => void acknowledge(event)} className="space-y-3 border-t border-border pt-3"><p className="text-sm font-medium">Acknowledge: {labels[selected.code]}</p><label className="block text-sm">Investigation note<textarea required minLength={8} maxLength={500} value={reason} disabled={saving} onChange={(event) => setReason(event.target.value)} className="mt-1 block min-h-20 w-full rounded-xl border border-border-strong bg-surface p-3" /></label><p className="text-xs text-muted">Acknowledging records your response. The alert stays active until fresh samples confirm recovery.</p>{saveError && <p role="alert" className="text-sm text-danger">{saveError}</p>}<div className="flex flex-wrap gap-2"><Button type="submit" loading={saving} disabled={reason.trim().length < 8}>Confirm acknowledgement</Button><Button variant="secondary" disabled={saving} onClick={() => setSelected(null)}>Cancel acknowledgement</Button></div></form>}
  </div>;
}
