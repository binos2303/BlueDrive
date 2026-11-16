"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Pencil, Plus, ShieldCheck, Trash2 } from "lucide-react";
import Dialog from "@/components/ui/Dialog";
import { requestAccountApi, accountCsrfHeaders } from "@/lib/account-service";

type Plan = { code: string; name: string; scope: "personal" | "workspace"; limit_bytes: number; is_active: boolean; assignments: number };
type Policy = { warning_percent: number; critical_percent: number };
type FormPlan = { code: string; name: string; scope: "personal" | "workspace"; limit_mib: string; is_active: boolean; reason: string };
const MIB = 1024 ** 2;
const initial = (): FormPlan => ({ code: "", name: "", scope: "personal", limit_mib: "100", is_active: true, reason: "" });
const errorMessage = (e: unknown) => e instanceof Error ? e.message : "Request failed.";
const readable = (bytes: number | null) => bytes === null ? "Unlimited" : `${new Intl.NumberFormat("en-US").format(bytes / MIB)} MiB`;
const toBytes = (mib: string) => {
  const n = Number(mib);
  return Number.isSafeInteger(n) && n >= 0 && n <= 1000000000 ? n * MIB : null;
};

export default function QuotaPlanPolicies({ canEdit }: { canEdit: boolean }) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [form, setForm] = useState<FormPlan>(initial);
  const [policyReason, setPolicyReason] = useState("");
  const [warning, setWarning] = useState("80");
  const [critical, setCritical] = useState("95");
  const [showInactive, setShowInactive] = useState(false);
  const [deleting, setDeleting] = useState<Plan | null>(null);
  const [deleteReason, setDeleteReason] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      requestAccountApi<{ plans: Plan[] }>(`/accounts/api/admin/quota-plans/${showInactive ? "?include_inactive=1" : ""}`, { signal: controller.signal, cache: "no-store" }),
      requestAccountApi<Policy>("/accounts/api/admin/quota-policy/", { signal: controller.signal, cache: "no-store" }),
    ]).then(([planResult, policyResult]) => {
      if (controller.signal.aborted) return;
      setPlans(planResult.plans);
      setPolicy(policyResult);
      setWarning(String(policyResult.warning_percent)); setCritical(String(policyResult.critical_percent));
      setError("");
    }).catch((err: unknown) => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision, showInactive]);

  function openPlan(plan?: Plan) {
    setNotice(""); setError("");
    setEditing(plan ? plan.code : "new");
    setForm(plan ? {
      code: plan.code, name: plan.name, scope: plan.scope,
      limit_mib: String(plan.limit_bytes / MIB), is_active: plan.is_active, reason: "",
    } : initial());
  }

  async function savePlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing || saving) return;
    const size = toBytes(form.limit_mib);
    if (size === null || form.reason.trim().length < 8 || form.reason.trim().length > 500) {
      setError("Use a whole MiB value and a reason of 8–500 characters."); return;
    }
    setSaving(true); setError("");
    const creating = editing === "new";
    try {
      const headers = await accountCsrfHeaders();
      const endpoint = creating ? "/accounts/api/admin/quota-plans/create/" : `/accounts/api/admin/quota-plans/${encodeURIComponent(editing)}/`;
      await requestAccountApi(endpoint, {
        method: creating ? "POST" : "PATCH", headers,
        body: JSON.stringify({ ...(creating ? { code: form.code.trim(), scope: form.scope } : { is_active: form.is_active }),
          name: form.name.trim(), limit_bytes: size, reason: form.reason.trim() }),
      });
      setEditing(null); setNotice(creating ? "Plan created." : "Plan updated. Existing allocations are unchanged.");
      setRevision((r) => r + 1);
    } catch (e) { setError(errorMessage(e)); }
    finally { setSaving(false); }
  }

  async function savePolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const warn = Number(warning); const crit = Number(critical);
    if (!Number.isInteger(warn) || !Number.isInteger(crit) || !(1 <= warn && warn < crit && crit <= 100) || policyReason.trim().length < 8 || policyReason.trim().length > 500) {
      setError("Provide valid warning/critical percentages and a reason of 8–500 characters."); return;
    }
    setSaving(true); setError("");
    try {
      await requestAccountApi("/accounts/api/admin/quota-policy/update/", {
        method: "PATCH", headers: await accountCsrfHeaders(),
        body: JSON.stringify({ warning_percent: warn, critical_percent: crit, reason: policyReason.trim() }),
      });
      setNotice("Quota warning thresholds updated."); setPolicyReason(""); setRevision((r) => r + 1);
    } catch (e) { setError(errorMessage(e)); }
    finally { setSaving(false); }
  }

  async function deletePlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!deleting || saving || deleteReason.trim().length < 8 || deleteReason.trim().length > 500) return;
    setSaving(true); setError("");
    try {
      await requestAccountApi(`/accounts/api/admin/quota-plans/${encodeURIComponent(deleting.code)}/delete/`, {
        method: "DELETE", headers: await accountCsrfHeaders(),
        body: JSON.stringify({ reason: deleteReason.trim() }),
      });
      setNotice(`Plan ${deleting.name} deleted. Existing quota limits are unchanged.`);
      setDeleting(null); setDeleteReason(""); setRevision((r) => r + 1);
    } catch (e) { setError(errorMessage(e)); }
    finally { setSaving(false); }
  }

  return <div className="space-y-4">
    {notice && <p role="status" className="rounded-lg border border-border p-3 text-sm text-foreground">{notice}</p>}
    {error && !editing && !deleting && <p role="alert" className="rounded-lg border border-danger/50 p-3 text-sm text-danger">{error}</p>}
    <section className="overflow-hidden rounded-[18px] border border-border bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <h2 className="text-[14px] font-semibold">Storage plans</h2>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-[12px] text-muted"><input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />Show inactive</label>
          {canEdit && <button type="button" onClick={() => openPlan()} className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-[12px] font-medium"><Plus size={14} />Add plan</button>}
        </div>
      </div>
      {loading ? <p className="p-5 text-sm text-muted">Loading plans…</p> : <div className="overflow-x-auto"><table className="w-full min-w-150 text-left text-[13px]"><thead className="bg-background text-xs text-muted"><tr><th className="px-4 py-3">Plan</th><th className="px-4 py-3">Scope</th><th className="px-4 py-3">Limit</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Actions</th></tr></thead><tbody>
        {plans.map((plan) => <tr key={plan.code} className="border-t border-border/70"><td className="px-4 py-3"><strong>{plan.name}</strong><p className="text-[11px] text-muted">{plan.code}</p></td><td className="px-4 py-3">{plan.scope === "personal" ? "Personal Drive" : "Personal workspace"}</td><td className="px-4 py-3">{readable(plan.limit_bytes)}</td><td className="px-4 py-3">{plan.is_active ? "Active" : "Inactive"}</td><td className="px-4 py-3 text-right"><div className="flex items-center justify-end gap-2">{canEdit ? <>
          <button type="button" onClick={() => openPlan(plan)} className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-xs"><Pencil size={13} />Edit</button>
          {!(["free", "workspace-starter"].includes(plan.code)) && <button type="button" title={plan.assignments ? "Assigned plan: disable it first to hide without changing quotas" : "Delete unused plan"} disabled={plan.assignments > 0} onClick={() => { setDeleting(plan); setDeleteReason(""); setError(""); }} className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-xs text-danger disabled:cursor-not-allowed disabled:opacity-40"><Trash2 size={13} />Delete</button>}
        </> : "View only"}</div></td></tr>)}
      </tbody></table>{!plans.length && <p className="p-5 text-sm text-muted">No storage plans.</p>}</div>}
    </section>
    <section className="rounded-[18px] border border-border bg-surface p-4">
      <div className="flex items-center gap-2"><ShieldCheck size={17} className="text-brand-contrast"/><h2 className="text-[14px] font-semibold">Quota warning thresholds</h2></div>
      <form onSubmit={(e) => void savePolicy(e)} className="mt-4 flex flex-wrap items-end gap-3">
        <label className="w-32 text-[12px] text-muted">Warning (%)<input type="number" aria-label="Warning threshold" min={1} max={99} step={1} value={warning} onChange={(e) => setWarning(e.target.value)} disabled={!canEdit || saving} className="mt-1 h-10 w-full rounded-xl border border-border bg-background px-3 text-foreground" /></label>
        <label className="w-32 text-[12px] text-muted">Critical (%)<input type="number" aria-label="Critical threshold" min={2} max={100} step={1} value={critical} onChange={(e) => setCritical(e.target.value)} disabled={!canEdit || saving} className="mt-1 h-10 w-full rounded-xl border border-border bg-background px-3 text-foreground" /></label>
        {canEdit && <label className="min-w-50 flex-1 text-[12px] text-muted">Reason
          <input minLength={8} maxLength={500} value={policyReason} onChange={(e) => setPolicyReason(e.target.value)} required className="mt-1 h-10 w-full rounded-xl border border-border bg-background px-3 text-foreground" placeholder="Explain the quota threshold change" />
        </label>}
        {canEdit && <button type="submit" disabled={saving || !policy || policyReason.trim().length < 8} className="h-10 rounded-xl bg-brand-soft px-4 text-[12px] font-semibold text-brand-contrast disabled:opacity-50">Save thresholds</button>}
      </form>
    </section>
    {deleting && <Dialog open title={`Delete ${deleting.name}?`} onClose={() => setDeleting(null)} closeDisabled={saving}>
        <p className="mt-3 text-[12px] text-muted">Only unassigned plans can be permanently deleted. Assigned plans must be disabled instead; existing quota allocations remain unchanged.</p>
        {error && <p role="alert" className="mt-3 text-[12px] text-danger">{error}</p>}
        <form className="mt-4 space-y-3" onSubmit={(event) => void deletePlan(event)}>
          <label className="block text-[12px]">Reason (8–500 characters)<textarea required minLength={8} maxLength={500} value={deleteReason} onChange={(e) => setDeleteReason(e.target.value)} className="mt-1 min-h-20 w-full rounded-xl border border-border bg-background p-3" /></label>
          <div className="flex justify-end gap-2"><button type="button" disabled={saving} onClick={() => setDeleting(null)} className="rounded-lg border border-border px-4 py-2">Cancel</button><button type="submit" disabled={saving || deleteReason.trim().length < 8} className="rounded-lg border border-danger/40 px-4 py-2 text-danger">{saving ? "Deleting…" : "Delete plan"}</button></div>
        </form>
    </Dialog>}
    {editing && <Dialog open title={editing === "new" ? "Create plan" : "Edit plan"} onClose={() => setEditing(null)} closeDisabled={saving}>
        <form onSubmit={(e) => void savePlan(e)} className="mt-4 space-y-3 text-[12px]">
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <label className="block">Code<input required disabled={editing !== "new"} pattern="[a-z0-9]+(?:-[a-z0-9]+)*" maxLength={48} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} className="mt-1 h-10 w-full rounded-xl border border-border bg-background px-3"/></label>
          <label className="block">Name<input required minLength={2} maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1 h-10 w-full rounded-xl border border-border bg-background px-3"/></label>
          <label className="block">Scope<select disabled={editing !== "new"} value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value as FormPlan["scope"] })} className="mt-1 h-10 w-full rounded-xl border border-border bg-background px-3"><option value="personal">Personal Drive</option><option value="workspace">Personal workspace</option></select></label>
          <label className="block">Limit (MiB)<input type="number" min={0} step={1} required value={form.limit_mib} onChange={(e) => setForm({ ...form, limit_mib: e.target.value })} className="mt-1 h-10 w-full rounded-xl border border-border bg-background px-3" /></label>
          {editing !== "new" && <label className="flex items-center gap-2"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })}/>Active</label>}
          <label className="block">Reason (8–500 characters)<textarea required minLength={8} maxLength={500} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} className="mt-1 min-h-20 w-full rounded-xl border border-border bg-background p-3"/></label>
          <p className="text-[11px] text-muted">Editing a preset does not automatically change existing quota assignments.</p>
          <div className="flex justify-end gap-2"><button type="button" disabled={saving} onClick={() => setEditing(null)} className="rounded-lg border border-border px-4 py-2">Cancel</button><button type="submit" disabled={saving || form.reason.trim().length < 8} className="rounded-lg bg-brand-soft px-4 py-2 font-semibold text-brand-contrast">{saving ? "Saving…" : "Save"}</button></div>
        </form>
    </Dialog>}
  </div>;
}
