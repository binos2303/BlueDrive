"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import styles from "./AdminDirectory.module.css";
import { Plus, RefreshCw, Search, ShieldCheck, UserRound, Users } from "lucide-react";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import AdminSegmentTabs from "@/components/admin/AdminSegmentTabs";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";
import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import UserSessionsDialog from "@/components/admin/UserSessionsDialog";
import {
  getAdminUsers,
  getAdminUserOverview,
  type AdminUser as Account,
  type AdminUsersPage as Page,
  type AdminUserSort as UserSort,
} from "@/lib/admin-user-service";

type Tab = "users" | "admins";
type Status = "all" | "active" | "inactive";
type AdminAccess = { can_manage_admins: boolean; role: "super_admin" | "platform_admin" };
type Intent = { kind: "suspend" | "reactivate" | "disable" | "reinvite"; user: Account };

const formattedDate = (value: string | null) => value ? new Date(value).toLocaleString() : "Never";
const errorText = (error: unknown) => error instanceof Error ? error.message : "Request failed.";
const SORT_OPTIONS: Array<{ value: UserSort; label: string }> = [
  { value: "recent_signin", label: "Recent sign-in" },
  { value: "oldest_signin", label: "Oldest sign-in" },
  { value: "newest", label: "Newest joined" },
  { value: "oldest", label: "Oldest joined" },
  { value: "name_asc", label: "Username A–Z" },
  { value: "name_desc", label: "Username Z–A" },
];

export default function UserDirectory() {
  const [tab, setTab] = useState<Tab>("users");
  const [status, setStatus] = useState<Status>("all");
  const [sort, setSort] = useState<UserSort>("recent_signin");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [records, setRecords] = useState<Page | null>(null);
  const [overview, setOverview] = useState<{ users: { total: number; platform_admins: number } } | null>(null);
  const [access, setAccess] = useState<AdminAccess | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [intent, setIntent] = useState<Intent | null>(null);
  const [sessionUser, setSessionUser] = useState<Account | null>(null);
  const [showInvite, setShowInvite] = useState(false);
  const [inviteUsername, setInviteUsername] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const mutationPending = useRef(false);
  const [actionError, setActionError] = useState("");

  useEffect(() => {
    let cancelled = false;
    requestAccountApi<AdminAccess>("/accounts/api/admin/access/")
      .then((response) => { if (!cancelled) setAccess(response); })
      .catch(() => { if (!cancelled) setAccess(null); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getAdminUsers({ scope: tab, page, status, query: search, sort }, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setRecords(data);
        setLoading(false);
        setError("");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setLoading(false);
        setError(errorText(err));
      });
    return () => controller.abort();
  }, [tab, status, page, search, sort, revision]);

  useEffect(() => {
    const controller = new AbortController();
    getAdminUserOverview(controller.signal)
      .then((result) => { if (!controller.signal.aborted) setOverview(result); })
      .catch(() => { if (!controller.signal.aborted) setOverview(null); });
    return () => controller.abort();
  }, [revision]);

  function refresh() {
    setLoading(true); setRevision((current) => current + 1);
  }
  function changeTab(next: Tab) {
    setTab(next); setPage(1); setStatus("all"); setSort("recent_signin"); setSearch(""); setQuery("");
    setError(""); setNotice(""); refresh();
  }
  function searchAccounts(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSearch(query.trim()); setPage(1); refresh();
  }
  function closeModal() {
    if (mutationPending.current) return;
    setShowInvite(false); setIntent(null); setReason(""); setActionError("");
  }
  async function submitInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutationPending.current || !access?.can_manage_admins) return;
    mutationPending.current = true;
    setPending(true); setActionError("");
    try {
      const headers = await accountCsrfHeaders();
      await requestAccountApi("/accounts/api/admin/administrators/invite/", {
        method: "POST", headers,
        body: JSON.stringify({ username: inviteUsername.trim(), email: inviteEmail.trim(), reason: reason.trim() }),
      });
      setShowInvite(false); setReason(""); setInviteUsername(""); setInviteEmail("");
      setNotice("Invitation sent. The new administrator must set a password using the emailed link.");
      refresh();
    } catch (err: unknown) {
      setActionError(errorText(err));
    } finally { mutationPending.current = false; setPending(false); }
  }
  async function submitAction() {
    if (mutationPending.current || !intent || reason.trim().length < 8 || reason.trim().length > 500) return;
    mutationPending.current = true;
    setPending(true); setActionError("");
    try {
      const headers = await accountCsrfHeaders();
      const path = intent.kind === "disable" || intent.kind === "reinvite"
        ? `/accounts/api/admin/administrators/${intent.user.id}/${intent.kind}/`
        : `/accounts/api/admin/users/${intent.user.id}/${intent.kind}/`;
      await requestAccountApi(path, { method: "POST", headers, body: JSON.stringify({ reason: reason.trim() }) });
      setNotice(intent.kind === "disable" ? "Administrator disabled and sessions revoked." : intent.kind === "reinvite" ? "A new invitation was emailed. Older invitation links are invalidated." : intent.kind === "suspend" ? "User suspended." : "User reactivated.");
      setIntent(null); setReason(""); refresh();
    } catch (err: unknown) { setActionError(errorText(err)); }
    finally { mutationPending.current = false; setPending(false); }
  }

  const totalPages = Math.max(1, Math.ceil((records?.count ?? 0) / (records?.page_size || 20)));
  return <div className="space-y-5">
    <AdminPageHeader title="User Management" description="Manage user accounts and platform administrators. Collaboration access is managed through workspaces." actions={
      <div className="flex gap-2">
        {tab === "admins" && access?.can_manage_admins && <Button size="sm" onClick={() => { setActionError(""); setReason(""); setShowInvite(true); }}><Plus size={15}/>Add Administrator</Button>}
        <Button size="sm" variant="secondary" onClick={refresh} disabled={loading}><RefreshCw size={15} className={loading ? "animate-spin" : ""}/>Refresh</Button>
      </div>
    } />
    {notice && <p role="status" className="rounded-xl border border-border bg-surface px-4 py-3 text-sm text-success">{notice}</p>}
    <section className="overflow-hidden rounded-2xl border border-border bg-surface">
      <div className="space-y-4 border-b border-border px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <AdminSegmentTabs<Tab> value={tab} label="Account category" onChange={changeTab} tabs={[
            { value: "users", label: "Users", icon: <Users size={16} /> },
            { value: "admins", label: "Platform Admins", icon: <ShieldCheck size={15} /> },
          ]} />
          <span className="text-[12px] text-muted" aria-label={tab === "users" ? "Total users" : "Total admins"}>
            {tab === "users" ? "Total users" : "Total admins"}: <strong className="tabular-nums text-foreground">{tab === "users" ? (overview?.users.total ?? "—") : (overview?.users.platform_admins ?? "—")}</strong>
          </span>
        </div>
        <div className={styles.filterContainer}><div className={styles.filters}>
          <form data-admin-search-shell role="search" onSubmit={searchAccounts} className={`${styles.search} flex h-11 min-w-0 items-center gap-2 rounded-xl border border-border bg-background px-3`}>
            <Search size={16} className="text-muted"/>
            <input aria-label="Search accounts" className="min-w-0 flex-1 bg-transparent text-[13px] outline-none" placeholder="Search username or email" value={query} onChange={(event) => setQuery(event.target.value)}/>
            <button type="submit" className="min-h-10 shrink-0 rounded-lg px-2 text-[13px] font-semibold text-brand-contrast hover:bg-brand-soft">Search</button>
          </form>
          <label className={styles.filterLabel}>
            <span>Status</span>
            <select aria-label="Account status" className="h-11 rounded-xl border border-border bg-background px-3 text-[12px] text-foreground" value={status} onChange={(event) => { setStatus(event.target.value as Status); setPage(1); refresh(); }}>
              <option value="all">All statuses</option><option value="active">Enabled</option><option value="inactive">Disabled{tab === "admins" ? " / Invited" : ""}</option>
            </select>
          </label>
          <label className={styles.filterLabel}>
            <span>Sort by</span>
            <select aria-label="Sort accounts" className="h-11 rounded-xl border border-border bg-background px-3 text-[12px] text-foreground" value={sort} onChange={(event) => { setSort(event.target.value as UserSort); setPage(1); setLoading(true); }}>
              {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        </div></div>
        <Link href="/admin/workspaces" className="inline-flex min-h-10 items-center rounded-lg px-2 text-[13px] font-medium text-brand-contrast hover:bg-brand-soft">View workspace membership</Link>
      </div>
      {loading && <p role="status" className="py-12 text-center text-sm text-muted">Loading accounts…</p>}
      {error && !loading && <p role="alert" className="px-5 py-8 text-sm text-danger">{error}</p>}
      {!loading && !error && <div className="overflow-x-auto">
        <table className={`${styles.table} min-w-[1000px]`}>
          <colgroup><col className="w-[29%]" /><col className="w-[15%]" /><col className="w-[15%]" /><col className="w-[19%]" /><col className="w-[22%]" /></colgroup>
          <thead><tr><th scope="col">Account</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col">Last sign-in</th><th scope="col" className="text-right">Actions</th></tr></thead>
          <tbody>{records?.results.map((user) => <tr key={user.id}>
            <td><div className="flex min-w-0 items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-contrast"><UserRound size={18} /></span><div className="min-w-0"><p className="truncate font-semibold" title={user.username}>{user.username}</p><p className="mt-0.5 truncate text-xs text-muted" title={user.email}>{user.email || "No email"}</p></div></div></td>
            <td>{tab === "users" ? "User" : user.admin_role === "super_admin" ? "Super Admin" : "Platform Admin"}</td>
            <td><span className="inline-flex rounded-lg bg-background px-2.5 py-1 text-xs font-medium">{tab === "admins" && user.admin_status === "invited" ? "Invitation pending" : user.is_active ? "Enabled" : "Disabled"}</span></td>
            <td className="text-[13px] tabular-nums text-muted">{formattedDate(user.last_login)}</td>
            <td><div className={styles.rowActions}>
              {tab === "users" && <>
                <Button size="sm" variant="secondary" className={user.is_active ? "text-danger" : "text-brand-contrast"} onClick={() => { setReason(""); setActionError(""); setIntent({ kind: user.is_active ? "suspend" : "reactivate", user }); }}>{user.is_active ? "Suspend" : "Reactivate"}</Button>
                <Button size="sm" variant="secondary" onClick={() => setSessionUser(user)}>Sessions</Button>
              </>}
              {tab === "admins" && access?.can_manage_admins && user.admin_role === "platform_admin" && user.admin_status !== "disabled" && <Button size="sm" variant="secondary" className="text-danger" onClick={() => { setReason(""); setActionError(""); setIntent({ kind: "disable", user }); }}>Disable</Button>}
              {tab === "admins" && access?.can_manage_admins && user.admin_role === "platform_admin" && user.admin_status !== "active" && <Button size="sm" variant="secondary" onClick={() => { setReason(""); setActionError(""); setIntent({ kind: "reinvite", user }); }}>Reinvite</Button>}
            </div></td>
          </tr>)}</tbody>
        </table>
        {records?.results.length === 0 && <p className="px-5 py-10 text-center text-sm text-muted">No accounts match your filters.</p>}
      </div>}
      {!loading && !error && <div className="flex justify-between border-t border-border px-5 py-4 text-[12px]"><span className="text-muted">{records?.count ?? 0} accounts · Page {page} of {totalPages}</span><div className="flex gap-2"><button type="button" disabled={page === 1} onClick={() => { setPage(page - 1); setLoading(true); }} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Previous</button><button type="button" disabled={page >= totalPages} onClick={() => { setPage(page + 1); setLoading(true); }} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Next</button></div></div>}
    </section>
    {sessionUser && <UserSessionsDialog key={sessionUser.id} user={sessionUser} onClose={() => setSessionUser(null)} />}
    <Dialog open={showInvite} title="Add Platform Administrator" description="Create a separate account and email a one-time password setup link." onClose={closeModal} closeDisabled={pending}>
      <form className="space-y-4" onSubmit={(event) => void submitInvite(event)}>
        <label className="block text-[12px] font-semibold">Username<input disabled={pending} required minLength={3} maxLength={150} autoComplete="off" value={inviteUsername} onChange={(event) => setInviteUsername(event.target.value)} className="mt-2 h-10 w-full rounded-xl border border-border bg-background px-3 text-[13px] font-normal"/></label>
        <label className="block text-[12px] font-semibold">Email<input disabled={pending} required type="email" autoComplete="off" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} className="mt-2 h-10 w-full rounded-xl border border-border bg-background px-3 text-[13px] font-normal"/></label>
        <p className="text-[12px] leading-5 text-muted">Role: <strong>Platform Admin</strong>. Only Django staff Superusers can issue invitations. This account will have no My Drive and will not be a Django Superuser.</p>
        <label className="block text-[12px] font-semibold">Reason (8–500 characters)<textarea disabled={pending} required minLength={8} maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} className="mt-2 min-h-20 w-full rounded-xl border border-border bg-background p-3 text-[13px] font-normal"/></label>
        {actionError && <p role="alert" className="text-[12px] text-danger">{actionError}</p>}
        <div className="flex justify-end gap-2"><Button variant="secondary" disabled={pending} onClick={closeModal}>Cancel</Button><Button type="submit" loading={pending} disabled={reason.trim().length < 8}>Send invitation</Button></div>
      </form>
    </Dialog>
    <Dialog open={intent !== null} title={intent?.kind === "disable" ? `Disable ${intent.user.username}?` : intent?.kind === "reinvite" ? `Reinvite ${intent.user.username}?` : intent?.kind === "suspend" ? `Suspend ${intent.user.username}?` : `Reactivate ${intent?.user.username}?`} description="A reason is required and recorded in the administrator audit log." onClose={closeModal} closeDisabled={pending}>
      <div className="space-y-4">
        <p className="text-[12px] text-muted">{intent?.kind === "disable" ? "This administrator will be disabled, their password invalidated, and all database sessions revoked. Reactivation requires a new invitation." : intent?.kind === "reinvite" ? "A new setup link will be emailed. All previously issued links will stop working." : intent?.kind === "suspend" ? "The user will be suspended, and database sessions revoked. Files and Workspaces are preserved." : "The user will be able to sign in again."}</p>
        <label className="block text-[12px] font-semibold">Reason (8–500 characters)<textarea disabled={pending} value={reason} maxLength={500} onChange={(event) => setReason(event.target.value)} className="mt-2 min-h-20 w-full rounded-xl border border-border bg-background p-3 text-[13px] font-normal"/></label>
        {actionError && <p role="alert" className="text-[12px] text-danger">{actionError}</p>}
        <div className="flex justify-end gap-2"><Button variant="secondary" disabled={pending} onClick={closeModal}>Cancel</Button><Button variant={intent?.kind === "reactivate" ? "primary" : "destructive"} loading={pending} disabled={reason.trim().length < 8 || reason.trim().length > 500} onClick={() => void submitAction()}>{intent?.kind === "reactivate" ? "Reactivate" : intent?.kind === "reinvite" ? "Send new invitation" : "Confirm"}</Button></div>
      </div>
    </Dialog>
  </div>;
}
