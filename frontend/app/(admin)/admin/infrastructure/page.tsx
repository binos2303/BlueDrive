import Link from "next/link";
import { Activity, ArrowRight, Cpu, Database, HardDrive, MemoryStick, Server } from "lucide-react";

const metrics = [
  { name: "CPU utilization", value: "Unknown", icon: Cpu },
  { name: "Memory usage", value: "Unknown", icon: MemoryStick },
  { name: "Disk capacity", value: "Unknown", icon: HardDrive },
];
const services = [
  { name: "Django backend", href: "/admin/infrastructure/servers" },
  { name: "PostgreSQL database", href: "/admin/infrastructure/database" },
  { name: "File storage", href: "/admin/infrastructure/storage" },
  { name: "MinIO", href: "/admin/infrastructure/minio" },
];

export default function InfrastructurePage() {
  return (
    <div>
      <div className="mb-5">
        <h2 className="text-2xl font-semibold tracking-tight">Infrastructure Overview</h2>
      </div>

      <div className="mb-5 grid gap-4 md:grid-cols-3">
        {metrics.map(({ name, value, icon: Icon }) => (
          <section key={name} className="rounded-[22px] border border-border bg-surface p-5">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted">{name}</p>
              <span className="rounded-xl bg-brand-soft p-2.5 text-brand"><Icon size={19} /></span>
            </div>
            <p className="mt-4 text-2xl font-semibold">{value}</p>
          </section>
        ))}
      </div>

      <section className="overflow-hidden rounded-[22px] border border-border bg-surface">
        <div className="border-b border-border p-5"><h3 className="font-semibold">Service status</h3></div>
        {services.map((service) => (
          <Link key={service.name} href={service.href} className="flex items-center gap-3 border-b border-border/70 px-5 py-4 last:border-0 hover:bg-background">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand">
              {service.name.includes("database") ? <Database size={18} /> : <Server size={18} />}
            </span>
            <span className="min-w-0 flex-1 text-sm font-medium">{service.name}</span>
            <span className="rounded-full bg-background px-2.5 py-1 text-xs font-medium text-muted">Unknown</span>
            <ArrowRight size={16} className="text-muted" />
          </Link>
        ))}
      </section>

      <section className="mt-5 rounded-[22px] border border-border bg-surface p-5">
        <div className="flex items-center gap-2">
          <Activity size={18} className="text-brand" />
          <h3 className="font-semibold">Recent alerts</h3>
        </div>
        <p className="mt-3 text-sm text-muted">Unknown</p>
      </section>
    </div>
  );
}
