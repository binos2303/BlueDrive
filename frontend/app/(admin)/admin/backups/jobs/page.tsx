import { AlertTriangle, Database, FileStack, Settings2 } from "lucide-react";

const jobs = [
  { name: "PostgreSQL Database", scope: "Database, metadata & permissions", icon: Database },
  { name: "User Files & Folders", scope: "Files", icon: FileStack },
  { name: "System Configuration", scope: "Configuration", icon: Settings2 },
];

export default function BackupJobsPage() {
  return (
    <div>
      <div className="mb-5 flex items-center justify-between gap-3">
        <h2 className="text-2xl font-semibold">Backup Jobs</h2>
        <button type="button" disabled className="rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white opacity-50">Run backup</button>
      </div>

      <div className="mb-4 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
        <AlertTriangle size={18} className="mt-0.5 shrink-0" />
        <p className="text-sm">Backup execution is unavailable.</p>
      </div>

      <section className="overflow-hidden rounded-[22px] border border-border bg-surface">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[840px] text-left">
            <thead className="bg-background text-[11px] font-semibold tracking-wide text-muted">
              <tr>
                <th className="px-5 py-3">JOB</th><th className="px-4 py-3">TYPE</th><th className="px-4 py-3">STATUS</th><th className="px-4 py-3">STARTED</th><th className="px-4 py-3">FINISHED</th><th className="px-4 py-3">SIZE</th><th className="px-4 py-3">ERROR</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(({ name, scope, icon: Icon }) => (
                <tr key={name} className="border-t border-border/70">
                  <td className="px-5 py-4"><span className="flex items-center gap-3 text-sm font-medium"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-soft text-brand"><Icon size={17} /></span>{name}</span></td>
                  <td className="px-4 py-4 text-sm text-muted">{scope}</td>
                  <td className="px-4 py-4"><span className="rounded-full bg-background px-2.5 py-1 text-xs text-muted">Unknown</span></td>
                  <td className="px-4 py-4 text-sm text-muted">—</td>
                  <td className="px-4 py-4 text-sm text-muted">—</td>
                  <td className="px-4 py-4 text-sm text-muted">—</td>
                  <td className="px-4 py-4 text-sm text-muted">—</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
