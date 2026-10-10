"use client";

import { useState } from "react";
import { Search } from "lucide-react";

export default function BackupHistoryPage() {
  const [type, setType] = useState("All types");
  const [status, setStatus] = useState("All statuses");
  const [period, setPeriod] = useState("Any time");

  return (
    <div>
      <div className="mb-5 flex items-center justify-between gap-3">
        <h2 className="text-2xl font-semibold tracking-tight">Backup History</h2>
        <span className="rounded-full bg-background px-2.5 py-1 text-xs text-muted">Unknown records</span>
      </div>

      <section className="mb-4 grid gap-3 rounded-[20px] border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex h-10 items-center gap-2 rounded-xl border border-border bg-background px-3 text-muted">
          <Search size={15} /><input aria-label="Search backups" placeholder="Search backup ID" className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted" />
        </label>
        <Filter label="Backup type" value={type} onChange={setType} options={["All types", "Database", "Files", "Full", "Configuration"]} />
        <Filter label="Status" value={status} onChange={setStatus} options={["All statuses", "Success", "Failed", "In Progress"]} />
        <Filter label="Time period" value={period} onChange={setPeriod} options={["Any time", "24 hours", "7 days", "30 days"]} />
      </section>

      <section className="overflow-hidden rounded-[22px] border border-border bg-surface">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[950px] text-left">
            <thead className="bg-background text-[11px] font-semibold tracking-wide text-muted">
              <tr>
                <th className="px-5 py-3">BACKUP ID</th><th className="px-4 py-3">TYPE</th><th className="px-4 py-3">CREATED AT</th><th className="px-4 py-3">SIZE</th><th className="px-4 py-3">STATUS</th><th className="px-4 py-3">INTEGRITY</th><th className="px-4 py-3">ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td colSpan={7} className="px-5 py-14 text-center">
                  <p className="text-sm font-medium text-foreground">No backup records available</p>
                  <p className="mt-1 text-xs text-muted">History will appear when a backup service is connected.</p>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between border-t border-border px-5 py-3 text-xs text-muted">
          <span>— records</span><span>Page — of —</span>
        </div>
      </section>
    </div>
  );
}

function Filter({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: string[] }) {
  return (
    <div>
      <label className="sr-only" htmlFor={`backup-filter-${label}`}>{label}</label>
      <select id={`backup-filter-${label}`} value={value} onChange={(event) => onChange(event.target.value)} className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm text-foreground outline-none">
        {options.map((option) => <option key={option}>{option}</option>)}
      </select>
    </div>
  );
}
