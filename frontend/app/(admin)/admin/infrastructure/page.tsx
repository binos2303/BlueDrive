"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import { ArrowRight, Database, HardDrive, Server } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

export default function InfrastructurePage() {
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiBase}/accounts/api/admin/overview/`, { credentials: "include", cache: "no-store", signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Unable to verify system health (HTTP ${response.status}).`);
        return response.json();
      }).then(() => {
        if (!controller.signal.aborted) { setConnected(true); setLoading(false); }
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : "Health check failed."); setLoading(false); }
      });
    return () => controller.abort();
  }, []);

  return <div className="space-y-5">
    <AdminPageHeader title="System Health" />
    {error && <p role="alert" className="rounded-xl border border-danger/30 bg-surface p-4 text-sm text-danger">{error}</p>}
    <section className="overflow-hidden rounded-[20px] border border-border bg-surface"><h3 className="border-b border-border px-5 py-4 text-[14px] font-semibold">Current visibility</h3>
      <div className="flex items-center gap-3 border-b border-border/60 px-5 py-4"><Server size={18} className="text-brand-contrast" /><div className="flex-1"><p className="text-[13px] font-medium">Django API</p><p className="mt-1 text-xs text-muted">Platform overview endpoint</p></div><span className="text-xs font-semibold">{loading ? "Checking…" : connected ? "Responding" : "Unavailable"}</span></div>
      <div className="flex items-center gap-3 border-b border-border/60 px-5 py-4"><Database size={18} className="text-brand-contrast" /><div className="flex-1"><p className="text-[13px] font-medium">PostgreSQL</p><p className="mt-1 text-xs text-muted">Database queries executed by overview API</p></div><span className="text-xs font-semibold">{loading ? "Checking…" : connected ? "Responding" : "Not verified"}</span></div>
      <div className="flex items-center gap-3 px-5 py-4"><HardDrive size={18} className="text-muted" /><div className="flex-1"><p className="text-[13px] font-medium">MinIO and host storage</p><p className="mt-1 text-xs text-muted">No connected device telemetry</p></div><span className="text-xs text-muted">Not monitored</span></div>
    </section>
    <p className="text-[12px] text-muted">A responding API is not a full uptime check. CPU, RAM, individual disks, cluster capacity and backup health require dedicated metrics and monitoring agents.</p>
    <Link href="/admin/infrastructure/topology" className="inline-flex items-center gap-2 text-[13px] font-semibold text-brand-contrast hover:underline">Storage Topology<ArrowRight size={15} /></Link>
  </div>;
}
