"use client";

import { useState } from "react";
import { ArrowLeftRight, ArrowRightLeft, ShieldCheck, X } from "lucide-react";

type Role = "Administrator" | "Infrastructure Manager" | "Team Leader" | "Member" | "Auditor";
type Assignment = { id: string; name: string; role: Role };

const initialAssignments: Assignment[] = [
  { id: "BD-10021", name: "Olivia Martin", role: "Administrator" },
  { id: "BD-10022", name: "Ethan Wilson", role: "Team Leader" },
  { id: "BD-10023", name: "Ava Thompson", role: "Member" },
  { id: "BD-10027", name: "Taylor Kim", role: "Infrastructure Manager" },
  { id: "BD-10025", name: "Mia Chen", role: "Auditor" },
];

export default function RoleAssignments() {
  const [assignments, setAssignments] = useState(initialAssignments);
  const [firstId, setFirstId] = useState(initialAssignments[0].id);
  const [secondId, setSecondId] = useState(initialAssignments[1].id);
  const [operation, setOperation] = useState<"transfer" | "swap" | null>(null);
  const [notice, setNotice] = useState("");
  const first = assignments.find((user) => user.id === firstId);
  const second = assignments.find((user) => user.id === secondId);
  const canApply = first && second && first.id !== second.id;

  function confirmOperation() {
    if (!operation || !first || !second) return;
    if (operation === "swap") {
      setAssignments((current) => current.map((user) => (
        user.id === first.id ? { ...user, role: second.role }
          : user.id === second.id ? { ...user, role: first.role }
            : user
      )));
      setNotice("Role swap complete");
    } else {
      setAssignments((current) => current.map((user) => (
        user.id === first.id ? { ...user, role: "Member" }
          : user.id === second.id ? { ...user, role: first.role }
            : user
      )));
      setNotice("Role transfer complete");
    }
    setOperation(null);
  }

  return (
    <section className="mt-5 rounded-[22px] border border-border bg-surface p-5 sm:p-6">
      <div className="flex items-start gap-3">
        <span className="rounded-xl bg-brand-soft p-2.5 text-brand"><ShieldCheck size={18} /></span>
        <div>
          <h3 className="font-semibold">Role transfer & swap</h3>
        </div>
      </div>

      {notice && <div role="status" className="mt-4 flex items-start justify-between gap-3 rounded-xl bg-brand-soft p-3 text-xs text-brand-hover"><span>{notice}</span><button type="button" aria-label="Dismiss" onClick={() => setNotice("")}><X size={15} /></button></div>}

      <div className="mt-5 grid gap-3 md:grid-cols-[1fr_auto_1fr] md:items-end">
        <label className="block text-xs font-medium text-muted">From
          <select value={firstId} onChange={(event) => setFirstId(event.target.value)} className="mt-1.5 h-10 w-full rounded-xl border border-border bg-surface px-3 text-sm text-foreground">
            {assignments.map((user) => <option key={user.id} value={user.id}>{user.name} · {user.role}</option>)}
          </select>
        </label>
        <div className="flex gap-2">
          <button type="button" disabled={!canApply} onClick={() => setOperation("transfer")} className="flex h-10 items-center gap-2 rounded-xl border border-border px-3 text-xs font-medium disabled:opacity-40"><ArrowRightLeft size={15} /> Transfer</button>
          <button type="button" disabled={!canApply} onClick={() => setOperation("swap")} className="flex h-10 items-center gap-2 rounded-xl border border-border px-3 text-xs font-medium disabled:opacity-40"><ArrowLeftRight size={15} /> Swap</button>
        </div>
        <label className="block text-xs font-medium text-muted">To
          <select value={secondId} onChange={(event) => setSecondId(event.target.value)} className="mt-1.5 h-10 w-full rounded-xl border border-border bg-surface px-3 text-sm text-foreground">
            {assignments.map((user) => <option key={user.id} value={user.id}>{user.name} · {user.role}</option>)}
          </select>
        </label>
      </div>

      {operation && first && second && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/35 p-4">
          <section role="dialog" aria-modal="true" aria-labelledby="role-preview-title" className="w-full max-w-md rounded-[22px] border border-border bg-surface p-6 shadow-xl">
            <div className="flex items-start justify-between">
              <div><h3 id="role-preview-title" className="text-lg font-semibold">Review role change</h3></div>
              <button type="button" aria-label="Close dialog" onClick={() => setOperation(null)} className="rounded-lg p-2 text-muted hover:bg-background"><X size={17} /></button>
            </div>
            <div className="mt-5 space-y-3 rounded-xl bg-background p-4 text-sm">
              <p>{first.name}: <strong>{first.role}</strong> {operation === "transfer" ? "→ Member" : `→ ${second.role}`}</p>
              <p>{second.name}: <strong>{second.role}</strong> → <strong>{first.role}</strong></p>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" onClick={() => setOperation(null)} className="rounded-xl border border-border px-4 py-2.5 text-sm font-medium">Cancel</button>
              <button type="button" onClick={confirmOperation} className="rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-hover">Confirm</button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
