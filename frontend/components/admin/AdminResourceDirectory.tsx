"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Plus, RefreshCw, Search } from "lucide-react";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";
import Input from "@/components/ui/Input";
import { AccountServiceError, requestAccountApi } from "@/lib/account-service";
import { provisionOrganization, reinviteOrganizationAdministrator, type OrganizationDirectory as Directory, type OrganizationDirectoryRow as Organization } from "@/lib/organization-admin-service";
import { finiteQuotaBytes } from "@/lib/organization-account-policy";
import styles from "./AdminDirectory.module.css";

const emptyForm = { name: "", slug: "", username: "", email: "", organizationQuota: "0", memberQuota: "0", reason: "" };

export default function AdminResourceDirectory() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<Directory | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [formError, setFormError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);
  const [reinvite, setReinvite] = useState<Organization | null>(null);
  const [actionReason, setActionReason] = useState("");
  const mutationPending = useRef(false);
  const attempt = useRef<{ payload: string; key: string } | null>(null);
  const canCreate = data?.capabilities?.createOrganization === true;
  const canReinvite = data?.capabilities?.reinviteOrganization === true;
  const hasActions = canCreate || canReinvite;

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ page: String(page), q: search });
    requestAccountApi<Directory>(`/accounts/api/admin/organizations/?${params}`, { cache: "no-store", signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) { setData(result); setError(""); setLoading(false); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted) { setData(null); setError(reason instanceof Error ? reason.message : "Unable to load organizations."); setLoading(false); } });
    return () => controller.abort();
  }, [page, search, revision]);

  function refresh() { setLoading(true); setRevision((value) => value + 1); }
  function submitSearch(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setPage(1); setSearch(query.trim()); refresh(); }
  function openCreate() {
    setForm(emptyForm); setFormError(""); setFieldErrors({}); setNotice(""); attempt.current = null; setFormOpen(true);
  }
  async function saveOrganization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutationPending.current || !canCreate) return;
    setFormError(""); setFieldErrors({}); mutationPending.current = true; setPending(true);
    try {
      const input = { name: form.name.trim(), slug: form.slug.trim(), admin: { username: form.username.trim(), email: form.email.trim() },
        limit_bytes: finiteQuotaBytes(form.organizationQuota), member_limit_bytes: finiteQuotaBytes(form.memberQuota), reason: form.reason.trim() };
      const payload = JSON.stringify(input);
      // Retry cùng nội dung giữ key cũ khi response bị mất, không tạo identity lần hai.
      if (attempt.current?.payload !== payload) attempt.current = { payload, key: crypto.randomUUID() };
      const result = await provisionOrganization(input, attempt.current.key);
      setFormOpen(false); setForm(emptyForm); attempt.current = null;
      setNotice(`Organization created. Administrator invitation sent.${result.storageReady ? "" : " Storage is not ready; uploads remain unavailable."}`);
      refresh();
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : "Could not create the organization. Retry the same request.");
      if (cause instanceof AccountServiceError) setFieldErrors(cause.fieldErrors);
    } finally { mutationPending.current = false; setPending(false); }
  }
  async function sendInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutationPending.current || !reinvite || !canReinvite) return;
    mutationPending.current = true; setPending(true); setFormError("");
    try {
      await reinviteOrganizationAdministrator(reinvite.id, actionReason.trim());
      setReinvite(null); setNotice("A new administrator invitation was sent. Previous invitation links are no longer valid."); refresh();
    } catch (cause) { setFormError(cause instanceof Error ? cause.message : "Could not send the invitation. Retry."); }
    finally { mutationPending.current = false; setPending(false); }
  }
  function fieldError(name: string) { return fieldErrors[name]?.join(" ") ?? ""; }
  const totalPages = Math.max(1, Math.ceil((data?.count ?? 0) / (data?.page_size || 20)));

  return <div className="space-y-6">
    <AdminPageHeader title="Organization Management" description="View organizations and their active collaboration workspaces."
      actions={<div className="flex flex-wrap gap-2">{canCreate && <Button size="sm" onClick={openCreate}><Plus size={16} />Create organization</Button>}<Button size="sm" variant="secondary" disabled={loading} onClick={refresh}><RefreshCw size={16} className={loading ? "animate-spin" : ""} />Refresh</Button></div>} />
    {notice && <p role="status" className="rounded-xl border border-border bg-surface p-3 text-sm">{notice}</p>}
    <section className="overflow-hidden rounded-2xl border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4"><h2 className="text-sm font-semibold">Organizations <span className="ml-2 font-normal tabular-nums text-muted">{loading ? "Loading…" : data?.count ?? "Unavailable"}</span></h2><span className="text-xs text-muted">Newest first</span></div>
      <form data-admin-search-shell role="search" onSubmit={submitSearch} className="m-5 flex h-11 min-w-0 items-center gap-3 rounded-xl border border-border bg-background px-3">
        <Search size={17} className="shrink-0 text-muted" /><input value={query} maxLength={100} onChange={(event) => setQuery(event.target.value)} aria-label="Search organizations" placeholder="Search organization name" className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
        <button type="submit" className="min-h-10 shrink-0 rounded-lg px-2 text-[13px] font-semibold text-brand-contrast hover:bg-brand-soft">Search</button>
      </form>
      {loading ? <p className="p-10 text-center text-sm text-muted" role="status">Loading organizations…</p> : error ? <div className="flex flex-wrap items-center gap-3 p-5"><p role="alert" className="text-sm text-danger">{error}</p><Button size="sm" variant="secondary" onClick={refresh}>Try again</Button></div> : <div className="overflow-x-auto">
        <table className={`${styles.table} min-w-[720px]`}>
          <colgroup><col className={hasActions ? "w-[30%]" : "w-[40%]"} /><col className={hasActions ? "w-[12%]" : "w-[18%]"} /><col className={hasActions ? "w-[14%]" : "w-[18%]"} /><col className="w-[24%]" />{hasActions && <col className="w-[20%]" />}</colgroup>
          <thead><tr><th scope="col">Name</th><th scope="col" className="text-right">Workspaces</th><th scope="col">Status</th><th scope="col">Created</th>{hasActions && <th scope="col">Action</th>}</tr></thead>
          <tbody>{data?.results.map((item) => <tr key={item.id}><td><span className="block truncate font-semibold" title={item.name}>{item.name}</span></td><td className="text-right tabular-nums">{item.workspaces}</td><td className="capitalize">{item.status.replace(/_/g, " ")}</td><td className="text-muted">{new Date(item.created_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}</td>{hasActions && <td>{canReinvite && item.pendingAdministratorInvitation && <Button size="sm" variant="secondary" onClick={() => { setReinvite(item); setActionReason(""); setFormError(""); }}>Resend invitation</Button>}</td>}</tr>)}</tbody>
        </table>
        {data?.results.length === 0 && <p className="p-10 text-center text-sm text-muted">No organizations match your search.</p>}
      </div>}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-4 text-[13px]"><span className="text-muted">Page {page} of {totalPages}</span><div className="flex gap-2"><Button size="sm" variant="secondary" disabled={page <= 1 || loading} onClick={() => { setPage((value) => value - 1); setLoading(true); }}>Previous</Button><Button size="sm" variant="secondary" disabled={page >= totalPages || loading} onClick={() => { setPage((value) => value + 1); setLoading(true); }}>Next</Button></div></div>
    </section>
    <Dialog open={formOpen} title="Create organization" description="Invite an initial administrator and allocate finite storage limits." onClose={() => setFormOpen(false)} closeDisabled={pending}>
      <form onSubmit={(event) => void saveOrganization(event)} className="space-y-4">
        {formError && <p role="alert" className="text-sm text-danger">{formError}</p>}
        {([
          ["name", "Organization name", "text", "name"], ["slug", "Organization identifier", "text", "slug"],
          ["username", "Administrator username", "text", "admin.username"], ["email", "Administrator email", "email", "admin.email"],
          ["organizationQuota", "Organization storage limit (GiB)", "number", "limit_bytes"], ["memberQuota", "Initial administrator storage limit (GiB)", "number", "member_limit_bytes"],
        ] as const).map(([key, label, type, errorKey]) => <div key={key}>
          <label htmlFor={`organization-${key}`} className="block text-sm font-medium">{label}</label>
          <Input id={`organization-${key}`} className="mt-1" type={type} required min={type === "number" ? 0 : undefined} step={type === "number" ? 1 : undefined} maxLength={type === "email" ? 254 : key === "username" ? 150 : 255}
            autoComplete={type === "email" ? "email" : key === "username" ? "username" : "off"} disabled={pending} value={form[key]} invalid={Boolean(fieldError(errorKey))} aria-describedby={fieldError(errorKey) ? `organization-${key}-error` : undefined} onChange={(event) => setForm({ ...form, [key]: event.target.value })} />
          {fieldError(errorKey) && <p id={`organization-${key}-error`} className="mt-1 text-xs text-danger">{fieldError(errorKey)}</p>}
        </div>)}
        <p className="text-xs leading-5 text-muted">0 blocks uploads until storage is allocated. The administrator sets their own password using the emailed invitation.</p>
        <label className="block text-sm font-medium">Reason<textarea required minLength={8} maxLength={500} disabled={pending} value={form.reason} onChange={(event) => setForm({ ...form, reason: event.target.value })} className="mt-1 min-h-20 w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm" /></label>
        {fieldError("reason") && <p className="text-xs text-danger">{fieldError("reason")}</p>}
        <div className="flex justify-end gap-2"><Button variant="secondary" disabled={pending} onClick={() => setFormOpen(false)}>Cancel</Button><Button type="submit" loading={pending} disabled={form.reason.trim().length < 8}>Create organization</Button></div>
      </form>
    </Dialog>
    <Dialog open={reinvite !== null} title="Resend administrator invitation" description={`Send a fresh invitation for ${reinvite?.name ?? "this organization"}. Previous links will stop working.`} onClose={() => setReinvite(null)} closeDisabled={pending}>
      <form className="space-y-4" onSubmit={(event) => void sendInvitation(event)}>
        {formError && <p role="alert" className="text-sm text-danger">{formError}</p>}
        <label className="block text-sm font-medium">Reason<textarea required minLength={8} maxLength={500} value={actionReason} disabled={pending} onChange={(event) => setActionReason(event.target.value)} className="mt-1 min-h-20 w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm" /></label>
        <div className="flex justify-end gap-2"><Button variant="secondary" disabled={pending} onClick={() => setReinvite(null)}>Cancel</Button><Button type="submit" loading={pending} disabled={actionReason.trim().length < 8}>Send invitation</Button></div>
      </form>
    </Dialog>
  </div>;
}
