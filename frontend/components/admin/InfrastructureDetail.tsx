import { CircleHelp } from "lucide-react";

const sections: Record<string, { title: string; checks: string[] }> = {
  servers: {
    title: "Servers",
    checks: ["Server inventory", "Server roles", "CPU and memory", "Health check history"],
  },
  storage: {
    title: "Storage & Disks",
    checks: ["Capacity and filesystem", "Read/write health", "Storage errors", "Free space alerts"],
  },
  database: {
    title: "PostgreSQL Database",
    checks: ["Connection status", "Response time", "Connection pool", "Query health"],
  },
  minio: {
    title: "MinIO",
    checks: ["Endpoint connection", "Bucket status", "Capacity", "Read/write health"],
  },
  alerts: {
    title: "Alerts & Monitoring",
    checks: ["Active alerts", "Alert history", "Monitoring rules", "Notification status"],
  },
};

export default function InfrastructureDetail({ section }: { section: string }) {
  const details = sections[section] ?? sections.servers;
  return (
    <div>
      <div className="mb-5">
        <h2 className="text-2xl font-semibold tracking-tight">{details.title}</h2>
      </div>
      <section className="overflow-hidden rounded-[22px] border border-border bg-surface">
        <div className="border-b border-border p-5"><h3 className="font-semibold">Health checks</h3></div>
        <div className="divide-y divide-border/70">
          {details.checks.map((check) => (
            <div key={check} className="flex items-center justify-between gap-4 px-5 py-4">
              <div className="flex items-center gap-3">
                <CircleHelp size={17} className="text-muted" />
                <span className="text-sm">{check}</span>
              </div>
              <span className="rounded-full bg-background px-2.5 py-1 text-xs font-medium text-muted">Unknown</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
