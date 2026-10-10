"use client";

import { useState } from "react";
import { AlertTriangle, Save } from "lucide-react";

export default function BackupPoliciesPage() {
  const [frequency, setFrequency] = useState("Daily");
  const [retention, setRetention] = useState("30");
  const [destination, setDestination] = useState("Primary storage");
  const [integrityCheck, setIntegrityCheck] = useState(true);
  const [failureAlerts, setFailureAlerts] = useState(true);

  return (
    <div>
      <div className="mb-5 flex items-center justify-between gap-3">
        <h2 className="text-2xl font-semibold">Backup Policies</h2>
        <button type="button" disabled className="flex items-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white opacity-50">
          <Save size={16} /> Save policy
        </button>
      </div>

      <div className="mb-5 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
        <AlertTriangle size={18} className="mt-0.5 shrink-0" />
        <p className="text-sm">Policy controls are unavailable.</p>
      </div>

      <section className="max-w-3xl space-y-5 rounded-[22px] border border-border bg-surface p-5 sm:p-6">
        <label className="block text-sm font-medium">
          Backup frequency
          <select disabled value={frequency} onChange={(event) => setFrequency(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-border bg-background px-3 text-sm disabled:opacity-70">
            <option>Hourly</option><option>Daily</option><option>Weekly</option>
          </select>
        </label>

        <fieldset>
          <legend className="text-sm font-medium">Data included</legend>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {["PostgreSQL database (includes metadata & permissions)", "User files & folders", "System configuration"].map((item) => (
              <label key={item} className="flex items-center gap-2 rounded-xl bg-background p-3 text-sm text-foreground/80">
                <input type="checkbox" disabled defaultChecked className="accent-brand" />{item}
              </label>
            ))}
          </div>
        </fieldset>

        <label className="block text-sm font-medium">
          Retention period (days)
          <input disabled type="number" min="1" value={retention} onChange={(event) => setRetention(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-border bg-background px-3 text-sm disabled:opacity-70" />
        </label>

        <label className="block text-sm font-medium">
          Backup destination
          <select disabled value={destination} onChange={(event) => setDestination(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-border bg-background px-3 text-sm disabled:opacity-70">
            <option>Primary storage</option><option>Secondary storage</option><option>MinIO</option>
          </select>
        </label>

        <div className="space-y-3">
          <Toggle label="Integrity verification" checked={integrityCheck} onChange={setIntegrityCheck} />
          <Toggle label="Alert on backup failure" checked={failureAlerts} onChange={setFailureAlerts} />
        </div>
      </section>
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-xl bg-background px-4 py-3 text-sm">
      {label}
      <input disabled type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="h-4 w-4 accent-brand disabled:opacity-70" />
    </label>
  );
}
