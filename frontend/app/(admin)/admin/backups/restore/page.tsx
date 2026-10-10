"use client";

import { useState } from "react";
import { AlertTriangle, Check, FileStack, HardDrive, RotateCcw, UserRound } from "lucide-react";

const modes = [
  { id: "files", label: "File Restore", icon: FileStack },
  { id: "user", label: "User Data Restore", icon: UserRound },
  { id: "database", label: "Database Restore", icon: HardDrive },
  { id: "full", label: "Full System Restore", icon: RotateCcw },
] as const;

const scopes = ["Files", "Folders", "Metadata", "Permissions"];

export default function RestoreCenterPage() {
  const [mode, setMode] = useState<(typeof modes)[number]["id"]>("files");
  const [scope, setScope] = useState<string[]>(["Files"]);
  const [conflictPolicy, setConflictPolicy] = useState("Restore as a separate copy");
  const [confirmed, setConfirmed] = useState(false);

  function toggleScope(item: string) {
    setScope((current) => current.includes(item) ? current.filter((value) => value !== item) : [...current, item]);
  }

  return (
    <div>
      <div className="mb-5 flex items-center justify-between gap-3">
        <h2 className="text-2xl font-semibold tracking-tight">Restore Center</h2>
        <span className="rounded-full bg-background px-2.5 py-1 text-xs text-muted">Unavailable</span>
      </div>

      <div className="mb-5 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
        <AlertTriangle size={18} className="mt-0.5 shrink-0" />
        <div>
          <p className="text-sm font-semibold">Restore service unavailable</p>
          <p className="mt-1 text-xs">No backup source is connected. Restore operations are disabled.</p>
        </div>
      </div>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {modes.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" onClick={() => setMode(id)} aria-pressed={mode === id} className={`flex items-center gap-3 rounded-[18px] border p-4 text-left transition ${mode === id ? "border-brand bg-brand-soft text-brand" : "border-border bg-surface text-foreground hover:bg-background"}`}>
            <Icon size={19} /><span className="text-sm font-semibold">{label}</span>
          </button>
        ))}
      </section>

      <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
        <div className="space-y-5 rounded-[22px] border border-border bg-surface p-5 sm:p-6">
          <div>
            <h3 className="font-semibold">Restore source</h3>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              {mode === "user" && <Field label="User" value="No users available" />}
              <Field label="Backup point" value="No backup available" />
            </div>
          </div>

          {mode === "user" && (
            <fieldset>
              <legend className="text-sm font-semibold">Data scope</legend>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {scopes.map((item) => (
                  <label key={item} className="flex items-center gap-2 rounded-xl bg-background p-3 text-sm">
                    <input type="checkbox" checked={scope.includes(item)} onChange={() => toggleScope(item)} className="accent-brand" />{item}
                  </label>
                ))}
              </div>
            </fieldset>
          )}

          <label className="block text-sm font-semibold">
            Conflict handling
            <select value={conflictPolicy} onChange={(event) => setConflictPolicy(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-border bg-background px-3 text-sm font-normal">
              <option>Restore as a separate copy</option>
              <option>Skip existing items</option>
              <option>Overwrite existing items</option>
            </select>
          </label>

          {mode === "user" && <p className="rounded-xl bg-background p-3 text-xs text-muted">Account recovery and user data recovery are separate operations.</p>}

          <button type="button" disabled className="w-full rounded-xl bg-brand px-4 py-3 text-sm font-semibold text-white opacity-50">Preview restore</button>
        </div>

        <div className="space-y-5">
          <section className="rounded-[22px] border border-border bg-surface p-5 sm:p-6">
            <h3 className="font-semibold">Restore preview</h3>
            <div className="mt-4 space-y-3">
              <PreviewRow label="Items to restore" value="Unknown" />
              <PreviewRow label="Potential conflicts" value="Unknown" />
              <PreviewRow label="Data to overwrite" value="Unknown" />
              <PreviewRow label="Selected scope" value={mode === "user" ? (scope.length ? scope.join(", ") : "None") : modes.find((item) => item.id === mode)?.label ?? "Unknown"} />
              <PreviewRow label="Conflict handling" value={conflictPolicy} />
            </div>
          </section>

          <section className="rounded-[22px] border border-border bg-surface p-5 sm:p-6">
            <h3 className="font-semibold">Confirmation & progress</h3>
            <label className="mt-4 flex items-start gap-2 text-sm text-muted">
              <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5 accent-brand" />
              I reviewed the restore scope and impact.
            </label>
            <button type="button" disabled className="mt-4 w-full rounded-xl border border-border px-4 py-3 text-sm font-semibold text-muted disabled:opacity-50">Start restore</button>
            <div className="mt-4 flex items-center gap-2 text-xs text-muted"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-background"><Check size={12} /></span>Progress: Unknown</div>
          </section>

          <section className="rounded-[22px] border border-border bg-surface p-5 sm:p-6">
            <h3 className="font-semibold">Result & audit log</h3>
            <p className="mt-3 text-sm text-muted">No restore operations recorded.</p>
          </section>
        </div>
      </section>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <select disabled className="mt-2 h-11 w-full rounded-xl border border-border bg-background px-3 text-sm text-muted disabled:opacity-70"><option>{value}</option></select>
    </label>
  );
}

function PreviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border/70 pb-3 last:border-0 last:pb-0">
      <span className="text-sm text-muted">{label}</span><span className="max-w-[60%] text-right text-sm font-medium">{value}</span>
    </div>
  );
}
