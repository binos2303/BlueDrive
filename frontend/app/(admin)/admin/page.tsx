import Link from "next/link";
import {
  Activity,
  ArrowRight,
  Archive,
  Database,
  HardDrive,
  Server,
  ShieldAlert,
  Users,
  UsersRound,
} from "lucide-react";

const overview = [
  { label: "Users", value: "Unknown", icon: Users, href: "/admin/users" },
  { label: "Infrastructure", value: "Unknown", icon: Server, href: "/admin/infrastructure" },
  { label: "Storage capacity", value: "Unknown", icon: HardDrive, href: "/admin/infrastructure/quotas/capacity" },
  { label: "Active alerts", value: "Unknown", icon: ShieldAlert, href: "/admin/infrastructure/alerts" },
];

const services = [
  { name: "Django backend", href: "/admin/infrastructure/servers", icon: Server },
  { name: "PostgreSQL database", href: "/admin/infrastructure/database", icon: Database },
  { name: "File storage", href: "/admin/infrastructure/storage", icon: HardDrive },
  { name: "MinIO", href: "/admin/infrastructure/minio", icon: Database },
];

const shortcuts = [
  { label: "User Directory", href: "/admin/users", icon: Users },
  { label: "Quota Management", href: "/admin/infrastructure/quotas", icon: UsersRound },
  { label: "Activity & Audit", href: "/admin/activity", icon: Activity },
  { label: "Backup & Restore", href: "/admin/backups", icon: Archive },
];

export default function AdminPage() {
  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-semibold tracking-tight text-foreground">Dashboard</h2>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-4">
        {overview.map(({ label, value, icon: Icon, href }) => (
          <Link key={label} href={href} className="rounded-[20px] border border-border bg-surface p-5 transition hover:bg-background">
            <div className="flex items-start justify-between">
              <p className="text-sm text-muted">{label}</p>
              <span className="flex h-10 w-10 items-center justify-center rounded-[13px] bg-brand-soft text-brand"><Icon size={19} /></span>
            </div>
            <p className="mt-4 text-3xl font-semibold tracking-tight text-foreground">{value}</p>
          </Link>
        ))}
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[1.2fr_0.8fr]">
        <section className="overflow-hidden rounded-[22px] border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border p-5">
            <h3 className="font-semibold">Infrastructure health</h3>
            <Link href="/admin/infrastructure" className="flex items-center gap-1 text-sm font-semibold text-brand hover:text-brand-hover">View overview <ArrowRight size={15} /></Link>
          </div>
          <div className="divide-y divide-border/70">
            {services.map(({ name, href, icon: Icon }) => (
              <Link key={name} href={href} className="flex items-center gap-3 px-5 py-4 transition hover:bg-background">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand"><Icon size={18} /></span>
                <span className="min-w-0 flex-1 text-sm font-medium">{name}</span>
                <span className="rounded-full bg-background px-2.5 py-1 text-xs font-medium text-muted">Unknown</span>
                <ArrowRight size={15} className="text-muted" />
              </Link>
            ))}
          </div>
          <p className="border-t border-border bg-background px-5 py-3 text-xs text-muted">Monitoring data unavailable</p>
        </section>

        <div className="space-y-5">
          <Link href="/admin/infrastructure/quotas" className="block rounded-[22px] border border-border bg-surface p-5 transition hover:bg-background">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand"><UsersRound size={19} /></span>
                <h3 className="font-semibold">Quota Management</h3>
              </div>
              <ArrowRight size={17} className="text-muted" />
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <QuotaMetric label="User quota" />
              <QuotaMetric label="Team quota" />
            </div>
          </Link>

          <Link href="/admin/backups" className="block rounded-[22px] border border-border bg-surface p-5 transition hover:bg-background">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand"><Archive size={19} /></span>
                <h3 className="font-semibold">Backup status</h3>
              </div>
              <span className="rounded-full bg-background px-2.5 py-1 text-xs font-medium text-muted">Unknown</span>
            </div>
            <p className="mt-4 text-sm text-muted">Backup service unavailable</p>
          </Link>
        </div>
      </div>

      <section className="mt-5 overflow-hidden rounded-[22px] border border-border bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-5 sm:px-6">
          <h3 className="font-semibold">Quick access</h3>
          <Link href="/admin/audit" className="text-sm font-semibold text-brand hover:text-brand-hover">System audit logs <ArrowRight size={14} className="ml-1 inline" /></Link>
        </div>
        <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-4">
          {shortcuts.map(({ label, href, icon: Icon }) => (
            <Link key={label} href={href} className="flex items-center gap-3 rounded-xl bg-background p-4 text-sm font-medium transition hover:bg-brand-soft hover:text-brand">
              <Icon size={18} /><span className="flex-1">{label}</span><ArrowRight size={15} />
            </Link>
          ))}
        </div>
      </section>

      <section className="mt-5 rounded-[22px] border border-border bg-surface p-5 sm:p-6">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2"><Activity size={18} className="text-brand" /><h3 className="font-semibold">Recent activity</h3></div>
          <Link href="/admin/activity" className="text-sm font-semibold text-brand hover:text-brand-hover">View activity <ArrowRight size={14} className="ml-1 inline" /></Link>
        </div>
        <div className="mt-4 rounded-xl bg-background px-4 py-8 text-center">
          <p className="text-sm font-medium">Activity feed unavailable</p>
          <p className="mt-1 text-xs text-muted">No live activity source is connected.</p>
        </div>
      </section>
    </div>
  );
}

function QuotaMetric({ label }: { label: string }) {
  return (
    <div className="rounded-xl bg-background p-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-2 text-lg font-semibold">Unknown</p>
    </div>
  );
}
