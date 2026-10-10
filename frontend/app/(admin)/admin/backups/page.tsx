import Link from "next/link";
import { AlertTriangle, Archive, ArrowRight, Database, FileStack, RotateCcw } from "lucide-react";

const summary = [
  { label: "Total backups", value: "Unknown", icon: Archive },
  { label: "Last successful backup", value: "Unknown", icon: Database },
  { label: "Backup storage used", value: "Unknown", icon: FileStack },
];

export default function BackupsPage() {
  return (
    <div>
      <div className="mb-5 flex items-center justify-between gap-3">
        <h2 className="text-2xl font-semibold">Backup Overview</h2>
        <span className="rounded-full bg-background px-2.5 py-1 text-xs font-medium text-muted">Unknown</span>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {summary.map(({ label, value, icon: Icon }) => (
          <section key={label} className="rounded-[20px] border border-border bg-surface p-5">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted">{label}</p>
              <span className="rounded-xl bg-brand-soft p-2.5 text-brand"><Icon size={18} /></span>
            </div>
            <p className="mt-4 text-2xl font-semibold">{value}</p>
          </section>
        ))}
      </div>

      <section className="mt-5 overflow-hidden rounded-[22px] border border-border bg-surface">
        <div className="border-b border-border p-5"><h3 className="font-semibold">Backup sources</h3></div>
        <div className="grid gap-3 p-5">
          <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 px-4 text-[11px] font-semibold tracking-wide text-muted">
            <span>SOURCE</span><span>STATUS</span><span className="text-right">LATEST BACKUP</span>
          </div>
          <StatusRow label="PostgreSQL database (metadata & permissions included)" />
          <StatusRow label="File storage" />
          <StatusRow label="System configuration" />
        </div>
      </section>

      <div className="mt-5 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
        <AlertTriangle size={18} className="mt-0.5 shrink-0" />
        <div>
          <p className="text-sm font-semibold">Backup service unavailable</p>
          <p className="mt-1 text-xs">Status and metrics are Unknown until a backup service is connected.</p>
        </div>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-3">
        <Destination href="/admin/backups/jobs" icon={Database} title="Backup Jobs" />
        <Destination href="/admin/backups/history" icon={Archive} title="Backup History" />
        <Destination href="/admin/backups/restore" icon={RotateCcw} title="Restore Center" />
      </div>
    </div>
  );
}

function StatusRow({ label }: { label: string }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 rounded-xl bg-background px-4 py-3">
      <span className="text-sm">{label}</span>
      <span className="rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-muted">Unknown</span>
      <span className="text-right text-xs text-muted">Unknown</span>
    </div>
  );
}

function Destination({ href, icon: Icon, title }: { href: string; icon: typeof Database; title: string }) {
  return (
    <Link href={href} className="flex items-center gap-3 rounded-[20px] border border-border bg-surface p-4 transition hover:bg-background">
      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand"><Icon size={18} /></span>
      <span className="flex-1 text-sm font-semibold">{title}</span>
      <ArrowRight size={16} className="text-muted" />
    </Link>
  );
}
