"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { HardDrive, RefreshCw, Search } from "lucide-react";
import Dialog from "@/components/ui/Dialog";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import AdminSegmentTabs from "@/components/admin/AdminSegmentTabs";
import QuotaPlanPolicies from "@/components/admin/QuotaPlanPolicies";
import styles from "./QuotaManagement.module.css";
import directoryStyles from "./AdminDirectory.module.css";
import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";

type Quota = {
  id: string; limit_bytes: number | null; used_bytes: number; reserved_bytes: number;
  remaining_bytes: number | null; percentage: number | null; plan_code: string | null;
  status: "normal" | "warning" | "critical" | "full" | "over_quota";
};
type DirectoryRow = {
  scope: "personal" | "workspace"; id: string; name: string; detail: string;
  tenant_status: string; tenant_kind?: "personal" | "business";
  editable: boolean; quota: Quota | null;
};
type Directory = { count: number; page: number; page_size: number; results: DirectoryRow[] };
type Plan = { code: string; name: string; scope: "personal" | "workspace"; limit_bytes: number; is_active: boolean };
type Change = { selected: DirectoryRow; plan_code: string; reason: string };
type ConfigEvent = { id: string; created_at: string; actor: string; target?: string; action?: string; reason: string };
type ConfigAudit = { plan_change_count: number; policy_change_count: number; plan_changes: ConfigEvent[]; policy_changes: ConfigEvent[] };
type Audit = { id: string; actor: string; created_at: string; quota_account_id: string; old_limit_bytes: number | null; new_limit_bytes: number | null; old_plan_code: string; new_plan_code: string; reason: string };

const BASE = "/admin/infrastructure/quotas";
const fmt = (n: number) => new Intl.NumberFormat("en-US").format(n);
function readable(n: number | null): string {
  if (n === null) return "Unlimited";
  if (n < 1024) return `${n} B`;
  const unit = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let value = n; let index = 0;
  while (value >= 1024 && index < unit.length - 1) { value /= 1024; index++; }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${unit[index]}`;
}
function errorMessage(e: unknown) { return e instanceof Error ? e.message : "Request failed."; }
const sections = [
  { key: "policies", text: "Plans & Policies" },
  { key: "users", text: "Personal" },
  { key: "workspaces", text: "Personal workspaces" },
  { key: "capacity", text: "Audit" },
] as const;
const sortOptions = [
  { value: "name_asc", label: "Name A–Z" },
  { value: "name_desc", label: "Name Z–A" },
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
];

export default function QuotaManagement({ section = "overview" }: { section?: string }) {
  const active = section === "overview" ? "policies" : section;
  const scope = active === "workspaces" ? "workspace" : "personal";
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("name_asc");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [directory, setDirectory] = useState<Directory | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [plansLoading, setPlansLoading] = useState(true);
  const [plansError, setPlansError] = useState("");
  const [audit, setAudit] = useState<{ count: number; results: Audit[] } | null>(null);
  const [configAudit, setConfigAudit] = useState<ConfigAudit | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [change, setChange] = useState<Change | null>(null);
  const [saving, setSaving] = useState(false);
  const [changeError, setChangeError] = useState("");
  const [canEdit, setCanEdit] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const run = async () => {
      setLoading(true); setError("");
      setDirectory(null); setAudit(null); setConfigAudit(null);
      try {
        const params = new URLSearchParams({ scope, q: search, sort, page: String(page) });
        const endpoint = active === "policies" ? "/accounts/api/admin/quota-plans/" :
          active === "capacity" ? `/accounts/api/admin/quotas/history/?page=${page}` :
            `/accounts/api/admin/quotas/?${params}`;
        const result = await requestAccountApi<Directory | { plans: Plan[] } | { count: number; results: Audit[] }>(endpoint, { signal: controller.signal, cache: "no-store" });
        if (controller.signal.aborted) return;
        if (active === "policies") setPlans((result as { plans: Plan[] }).plans);
        else if (active === "capacity") {
          setAudit(result as { count: number; results: Audit[] });
          const config = await requestAccountApi<ConfigAudit>(`/accounts/api/admin/quotas/configuration-history/?page=${page}`, { signal: controller.signal, cache: "no-store" });
          if (!controller.signal.aborted) setConfigAudit(config);
        }
        else setDirectory(result as Directory);
      } catch (e) {
        if (!controller.signal.aborted) setError(errorMessage(e));
      } finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void run();
    return () => controller.abort();
  }, [scope, search, sort, page, revision, active]);

  useEffect(() => {
    const controller = new AbortController();
    requestAccountApi<{ can_manage_admins: boolean }>("/accounts/api/admin/access/", { signal: controller.signal })
      .then((access) => { if (!controller.signal.aborted) setCanEdit(access.can_manage_admins); })
      .catch(() => { if (!controller.signal.aborted) setCanEdit(false); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const startTimer = window.setTimeout(() => {
      if (!controller.signal.aborted) { setPlansLoading(true); setPlansError(""); }
    }, 0);
    requestAccountApi<{ plans: Plan[] }>("/accounts/api/admin/quota-plans/?include_inactive=1", { signal: controller.signal })
      .then((r) => { if (!controller.signal.aborted) { setPlans(r.plans); setPlansError(""); } })
      .catch((e) => { if (!controller.signal.aborted) setPlansError(errorMessage(e)); })
      .finally(() => { window.clearTimeout(startTimer); if (!controller.signal.aborted) setPlansLoading(false); });
    return () => { controller.abort(); window.clearTimeout(startTimer); };
  }, [active, revision]);

  function refresh() { setRevision((r) => r + 1); }
  function searchSubmit(e: FormEvent<HTMLFormElement>) { e.preventDefault(); setPage(1); setSearch(query.trim()); refresh(); }
  const totalPages = Math.max(1, Math.ceil((directory?.count ?? 0) / (directory?.page_size || 20)));
  const availablePlans = plans.filter((plan) => plan.is_active && plan.scope === change?.selected.scope);

  async function applyChange(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!change?.selected.quota || saving) return;
    setSaving(true); setChangeError(""); setNotice("");
    if (plansLoading || plansError || !availablePlans.some((plan) => plan.code === change.plan_code)) {
      setChangeError("Select an active storage plan before saving."); setSaving(false); return;
    }
    try {
      const headers = await accountCsrfHeaders();
      await requestAccountApi(`/accounts/api/admin/quotas/${change.selected.quota.id}/`, {
        method: "PATCH", headers,
        body: JSON.stringify({
          plan_code: change.plan_code,
          reason: change.reason.trim(),
        }),
      });
      setNotice(`Storage plan updated for ${change.selected.name}.`);
      setChange(null); refresh();
    } catch (e) { setChangeError(errorMessage(e)); }
    finally { setSaving(false); }
  }

  const title = "Quota Management";
  return <div className="space-y-5">
    <AdminPageHeader title={title} actions={<button type="button" onClick={refresh} disabled={loading} className="inline-flex h-10 items-center gap-2 rounded-xl border border-border bg-surface px-4 text-[13px] disabled:opacity-40"><RefreshCw size={15} className={loading ? "animate-spin" : ""} />Refresh</button>} />
    <AdminSegmentTabs value={active} label="Quota management sections" tabs={sections.map(({ key, text }) => ({ value: key, label: text, href: `${BASE}/${key}` }))} />
    {notice && <p role="status" className="rounded-xl border border-border bg-surface px-4 py-3 text-[13px] text-foreground">{notice}</p>}
    {error && !change && <p role="alert" className="rounded-xl border border-border bg-surface px-4 py-3 text-[13px] text-danger">{error}</p>}
    {(active === "users" || active === "workspaces") && <>
      <p className="text-[12px] text-muted">{active === "users" ? "Personal Drive accounts" : "Personal collaboration workspaces"}: <strong className="ml-1 tabular-nums text-foreground">{loading ? "—" : fmt(directory?.count || 0)}</strong></p>
      <section className="overflow-hidden rounded-[20px] border border-border bg-surface">
        <div className={`${styles.filterGrid} border-b border-border p-4`}>
          <form role="search" onSubmit={searchSubmit} className="flex h-11 min-w-0 items-center gap-2 rounded-xl border border-border bg-background px-3 focus-within:ring-2 focus-within:ring-brand-contrast/30"><Search size={16} className="shrink-0 text-muted"/><input aria-label="Search quotas" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={active === "users" ? "Search personal accounts" : "Search personal workspaces"} className="w-full min-w-0 bg-transparent text-[13px] outline-none focus:outline-none focus-visible:outline-none focus-visible:ring-0"/><button type="submit" className="shrink-0 text-[12px] font-semibold text-brand-contrast">Search</button></form>
          <select aria-label="Sort quotas" value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }} className="h-11 min-w-0 rounded-xl border border-border bg-background px-3 text-[13px] text-foreground">{sortOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
        </div>
        {loading ? <p role="status" className="p-8 text-center text-sm text-muted">Loading quota records…</p> : error ? null : <div className="overflow-x-auto">
          <table className={`${directoryStyles.table} min-w-[1160px]`}><colgroup><col className="w-[23%]" /><col className="w-[14%]" /><col className="w-[15%]" /><col className="w-[12%]" /><col className="w-[13%]" /><col className="w-[11%]" /><col className="w-[12%]" /></colgroup><thead className="bg-background text-xs text-muted"><tr><th className="px-5 py-4">{active === "users" ? "Account" : "Workspace"}</th><th className="px-4 py-4">Plan</th><th className="px-4 py-4">Used / Reserved</th><th className="px-4 py-4">Limit</th><th className="px-4 py-4">Usage</th><th className="px-4 py-4">Status</th><th className="px-5 py-4 text-right">Actions</th></tr></thead>
            <tbody>{directory?.results.map((row) => {
              const q = row.quota; const width = Math.max(0, Math.min(q?.percentage ?? 0, 100));
              return <tr key={row.id} className="border-t border-border/70">
                <td className="px-5 py-4"><p className="truncate font-semibold" title={row.name}>{row.name}</p><p className="mt-1 truncate text-xs text-muted" title={row.detail}>{row.detail}</p></td>
                <td className="px-4 py-4 text-muted">{plans.find((p) => p.code === q?.plan_code)?.name ?? (q?.plan_code || (q ? "Not assigned" : "Unconfigured"))}</td>
                <td className="px-4 py-4"><p>{q ? readable(q.used_bytes) : "—"}</p><p className="text-xs text-muted">Reserved: {q ? readable(q.reserved_bytes) : "—"}</p></td>
                <td className="px-4 py-4">{q ? readable(q.limit_bytes) : "—"}</td>
                <td className="px-4 py-4"><div className="h-2 w-full overflow-hidden rounded-full bg-background"><div className="h-full rounded-full bg-brand-contrast" style={{ width: `${width}%` }} /></div><p className="mt-1 text-xs text-muted">{q?.percentage === null || !q ? "—" : `${q.percentage}%`}</p></td>
                <td className="px-4 py-4 capitalize">{q?.status.replaceAll("_", " ") ?? "Unconfigured"}</td>
                <td className="px-5 py-4 text-right">{row.editable && q && canEdit ? <button type="button" onClick={() => {
                  setChangeError("");
                  setChange({ selected: row, plan_code: plans.some((p) => p.code === q.plan_code && p.is_active && p.scope === row.scope) ? q.plan_code! : "", reason: "" });
                }} className="rounded-xl border border-border px-3 py-2 text-xs font-semibold text-brand-contrast">Manage</button> : <span className="text-xs text-muted">{!q ? "Requires reconciliation" : "View only"}</span>}</td>
              </tr>;
            })}</tbody></table>{!directory?.results.length && <p className="p-8 text-center text-sm text-muted">No matching storage accounts.</p>}
          </div>}
        {!loading && !error && directory && <div className="flex items-center justify-between gap-3 border-t border-border p-4 text-xs text-muted"><span>Page {page} of {totalPages}</span><div className="flex gap-2"><button type="button" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)} className="rounded-lg border border-border px-3 py-2 disabled:opacity-30">Previous</button><button type="button" disabled={page >= totalPages || loading} onClick={() => setPage((p) => p + 1)} className="rounded-lg border border-border px-3 py-2 disabled:opacity-30">Next</button></div></div>}
      </section>
    </>}
    {active === "policies" && <QuotaPlanPolicies canEdit={canEdit} />}
    {active === "capacity" && !error && <section className="overflow-hidden rounded-[20px] border border-border bg-surface"><div className="flex items-center gap-2 border-b border-border px-5 py-4 text-[14px] font-semibold"><HardDrive size={17}/>Quota changes</div>{loading ? <p className="p-8 text-sm text-muted">Loading audit history…</p> : <div className="overflow-x-auto"><table className="w-full min-w-162.5 text-left text-[13px]"><thead className="bg-background text-xs text-muted"><tr><th className="px-5 py-3">Changed</th><th className="px-5 py-3">Administrator</th><th className="px-5 py-3">Old limit</th><th className="px-5 py-3">New limit</th><th className="px-5 py-3">Reason</th></tr></thead><tbody>{audit?.results.map((item) => <tr className="border-t border-border" key={item.id}><td className="px-5 py-4">{new Date(item.created_at).toLocaleString()}</td><td className="px-5 py-4">{item.actor}</td><td className="px-5 py-4">{readable(item.old_limit_bytes)}</td><td className="px-5 py-4">{readable(item.new_limit_bytes)}</td><td className="px-5 py-4">{item.reason}</td></tr>)}</tbody></table>{!audit?.results.length && <p className="p-8 text-center text-xs text-muted">No quota changes recorded.</p>}</div>}<div className="flex items-center justify-between border-t border-border p-4 text-xs"><span>{audit?.count ?? 0} events · Page {page}</span><div className="flex gap-2"><button disabled={page === 1} onClick={() => setPage((p) => p - 1)} className="rounded-lg border border-border px-3 py-2 disabled:opacity-30">Previous</button><button disabled={!audit || page * 20 >= audit.count} onClick={() => setPage((p) => p + 1)} className="rounded-lg border border-border px-3 py-2 disabled:opacity-30">Next</button></div></div></section>}
    {active === "capacity" && !loading && !error && configAudit && <section className="overflow-hidden rounded-[20px] border border-border bg-surface">
      <h2 className="border-b border-border px-4 py-3 text-[13px] font-semibold">Plan & policy changes</h2>
      <div className="overflow-x-auto"><table className="w-full min-w-160 text-left text-[12px]"><thead className="bg-background text-muted"><tr><th className="px-4 py-3">Changed</th><th className="px-4 py-3">Type</th><th className="px-4 py-3">Administrator</th><th className="px-4 py-3">Reason</th></tr></thead><tbody>
        {[...configAudit.plan_changes.map((e) => ({ ...e, type: `Plan ${e.target || ""} · ${e.action || "updated"}` })), ...configAudit.policy_changes.map((e) => ({ ...e, type: "Storage policy" }))].sort((a, b) => b.created_at.localeCompare(a.created_at)).map((event) => <tr key={event.id} className="border-t border-border/70"><td className="px-4 py-3">{new Date(event.created_at).toLocaleString()}</td><td className="px-4 py-3">{event.type}</td><td className="px-4 py-3">{event.actor}</td><td className="px-4 py-3">{event.reason}</td></tr>)}
      </tbody></table></div>
      <p className="border-t border-border px-4 py-3 text-xs text-muted">{configAudit.plan_change_count} plan changes · {configAudit.policy_change_count} policy changes. Page {page} for each change type.</p>
    </section>}
    {change && <Dialog open title="Assign storage plan" onClose={() => setChange(null)} closeDisabled={saving}>
      <p className="mt-2 text-[13px] text-muted">{change.selected.name}</p>
      <form onSubmit={(e) => void applyChange(e)} className="mt-5 space-y-4">
        {changeError && <p role="alert" className="text-sm text-danger">{changeError}</p>}
        {plansLoading ? <p role="status" className="text-sm text-muted">Loading storage plans…</p> : plansError ? (
          <div role="alert" className="text-sm text-danger"><p>Storage plans could not be loaded. {plansError}</p><button type="button" onClick={refresh} className="mt-2 underline">Refresh plans</button></div>
        ) : !availablePlans.length && <p className="text-sm text-muted">No active plan is available for this storage type.</p>}
        <label className="block text-[12px] font-medium">Storage plan
          <select required disabled={saving || plansLoading || Boolean(plansError)} className="mt-2 h-11 w-full rounded-xl border border-border bg-background px-3" value={change.plan_code} onChange={(e) => setChange({ ...change, plan_code: e.target.value })}>
            <option value="" disabled>Select a plan</option>
            {availablePlans.map((p) => <option key={p.code} value={p.code}>{p.name} — {readable(p.limit_bytes)}</option>)}
          </select>
        </label>
        {!saving && <Link href={`${BASE}/policies`} onClick={() => setChange(null)} className="inline-block text-xs font-medium text-brand-contrast underline">Manage plans</Link>}
        <label className="block text-[12px] font-medium">Reason (8–500 characters)<textarea disabled={saving} minLength={8} maxLength={500} required value={change.reason} onChange={(e) => setChange({ ...change, reason: e.target.value })} className="mt-2 min-h-24 w-full rounded-xl border border-border bg-background p-3" /></label>
        <p className="text-xs text-muted">The selected plan sets the storage limit. Changing plans never deletes files; uploads are blocked when capacity is insufficient.</p>
        <div className="flex justify-end gap-2">
          <button type="button" disabled={saving} onClick={() => setChange(null)} className="rounded-xl border border-border px-4 py-2.5 text-sm">Cancel</button>
          <button type="submit" disabled={saving || plansLoading || Boolean(plansError) || !availablePlans.some((p) => p.code === change.plan_code) || change.reason.trim().length < 8} className="rounded-xl bg-brand-soft px-4 py-2.5 text-sm font-semibold text-brand-contrast disabled:opacity-50">{saving ? "Saving…" : "Assign plan"}</button>
        </div>
      </form>
    </Dialog>}
  </div>;
}
