import AdminPageHeader from "@/components/admin/AdminPageHeader";
import Link from "next/link";
import { ArrowRight, Database, HardDrive, Network } from "lucide-react";
import StorageManager from "@/components/storage/StorageManager";

export default function StorageConnectionDiagnostics() {
  return <StorageManager fallback={<TopologyNotConnected />} />;
}

function TopologyNotConnected() {
  return <div className="space-y-5">
    <AdminPageHeader title="Storage Topology" />
    <section className="rounded-[20px] border border-border bg-surface p-6">
      <div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-contrast"><Network size={20} /></span><div><h3 className="text-[14px] font-semibold">Topology telemetry not connected</h3><p className="mt-1 text-[12px] text-muted">No verified physical nodes or devices can be displayed yet.</p></div></div>
      <p className="mt-5 max-w-3xl text-[13px] leading-6 text-muted">Object storage does not provide a complete hardware topology by itself. The map needs verified storage inventory and host telemetry before it can show real nodes and disks. No demo devices are displayed as real infrastructure.</p>
    </section>
    <div className="grid gap-4 md:grid-cols-2">
      <section className="rounded-[20px] border border-border bg-surface p-5"><div className="flex items-center gap-2"><Database size={17} className="text-brand-contrast" /><h3 className="text-sm font-semibold">Object storage monitoring</h3></div><p className="mt-3 text-[13px] text-muted">Connect authenticated provider metrics to report bucket capacity, service state and available node data.</p><p className="mt-3 text-[12px] font-medium">Status: Not configured</p></section>
      <section className="rounded-[20px] border border-border bg-surface p-5"><div className="flex items-center gap-2"><HardDrive size={17} className="text-brand-contrast" /><h3 className="text-sm font-semibold">Physical disk monitoring</h3></div><p className="mt-3 text-[13px] text-muted">Use a host agent such as Node Exporter, supplemented with SMART/RAID tooling, to report actual disks, disk health, CPU and RAM.</p><p className="mt-3 text-[12px] font-medium">Status: Not configured</p></section>
    </div>
    <Link href="/admin/infrastructure" className="inline-flex items-center gap-2 text-xs font-semibold text-brand-contrast hover:underline">System Health<ArrowRight size={14} /></Link>
  </div>;
}
