"use client";

import { useEffect, useState } from "react";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import UploadFinalizationStatus from "@/components/admin/UploadFinalizationStatus";
import Button from "@/components/ui/Button";
import { Database, HardDrive, RefreshCw, Server } from "lucide-react";
import { getAdminOverview, type AdminOverview } from "@/lib/admin-overview-service";

export default function InfrastructurePage() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    getAdminOverview(controller.signal).then((data) => {
        if (!controller.signal.aborted) { setOverview(data); setLoading(false); setError(""); }
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) { setOverview(null); setError(reason instanceof Error ? reason.message : "Health check failed."); setLoading(false); }
      });
    return () => controller.abort();
  }, [revision]);
  const connected = overview !== null;

  return <div className="space-y-5">
    <AdminPageHeader title="System Health" actions={<Button variant="secondary" size="sm" disabled={loading} onClick={() => { setOverview(null); setError(""); setLoading(true); setRevision((value) => value + 1); }}><RefreshCw size={15} className={loading ? "animate-spin" : ""} />Refresh</Button>} />
    {error && <p role="alert" className="rounded-xl border border-danger/30 bg-surface p-4 text-sm text-danger">{error}</p>}
    <section className="overflow-hidden rounded-[20px] border border-border bg-surface"><h3 className="border-b border-border px-5 py-4 text-[14px] font-semibold">Current visibility</h3>
      <div className="flex items-center gap-3 border-b border-border/60 px-5 py-4"><Server size={18} className="text-brand-contrast" /><div className="flex-1"><p className="text-[13px] font-medium">Django API</p><p className="mt-1 text-xs text-muted">Platform overview endpoint</p></div><span className="text-xs font-semibold">{loading ? "Checking…" : connected ? "Responding" : "Unavailable"}</span></div>
      <div className="flex items-center gap-3 border-b border-border/60 px-5 py-4"><Database size={18} className="text-brand-contrast" /><div className="flex-1"><p className="text-[13px] font-medium">PostgreSQL</p><p className="mt-1 text-xs text-muted">Database queries executed by overview API</p></div><span className="text-xs font-semibold">{loading ? "Checking…" : connected ? "Responding" : "Not verified"}</span></div>
      <div className="flex items-center gap-3 px-5 py-4"><HardDrive size={18} className="text-muted" /><div className="flex-1"><p className="text-[13px] font-medium">Object storage and hosts</p><p className="mt-1 text-xs text-muted">No connected device telemetry</p></div><span className="text-xs text-muted">Not monitored</span></div>
    </section>
    <p className="text-[12px] text-muted">A responding API is not a full uptime check. CPU, RAM, individual disks, cluster capacity and backup health require dedicated metrics and monitoring agents.</p>
    <UploadFinalizationStatus data={overview?.uploads} />
  </div>;
}
