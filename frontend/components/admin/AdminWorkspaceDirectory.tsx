"use client";

import { useEffect, useState, type FormEvent } from "react";
import { RefreshCw, Search } from "lucide-react";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import Button from "@/components/ui/Button";
import { getAdminWorkspaces, type AdminWorkspacePage } from "@/lib/admin-workspaces-service";
import type { AdminWorkspaceScope, AdminWorkspaceSort } from "@/lib/admin-workspaces-query";
import styles from "./AdminDirectory.module.css";

const sorts: Array<{ value: AdminWorkspaceSort; label: string }> = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "name_asc", label: "Name A–Z" },
  { value: "name_desc", label: "Name Z–A" },
];

export default function AdminWorkspaceDirectory() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState<AdminWorkspaceScope>("all");
  const [sort, setSort] = useState<AdminWorkspaceSort>("newest");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<AdminWorkspacePage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getAdminWorkspaces({ query: search, scope, sort, page }, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setResult(data); setError(""); setLoading(false);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setResult(null); setError(reason instanceof Error ? reason.message : "Unable to load workspaces."); setLoading(false);
      });
    return () => controller.abort();
  }, [search, scope, sort, page, revision]);

  function refresh() { setLoading(true); setRevision((value) => value + 1); }
  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setPage(1); setSearch(query.trim()); refresh();
  }
  function changePage(next: number) { setLoading(true); setPage(next); }
  const totalPages = Math.max(1, Math.ceil((result?.count ?? 0) / (result?.page_size || 20)));

  return <div className="space-y-6">
    <AdminPageHeader title="Workspace Management" description="Browse personal and organization workspaces. Workspace managers control their members and invitations."
      actions={<Button size="sm" variant="secondary" disabled={loading} onClick={refresh}><RefreshCw size={16} className={loading ? "animate-spin" : ""} />Refresh</Button>} />
    <section className="overflow-hidden rounded-2xl border border-border bg-surface" aria-label="Workspace directory">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
        <h2 className="text-sm font-semibold">Workspaces <span className="ml-2 font-normal tabular-nums text-muted">{loading ? "Loading…" : result ? result.count : "Unavailable"}</span></h2>
        <span className="text-xs text-muted">Read-only directory</span>
      </div>
      <div className={`${styles.filterContainer} border-b border-border p-5`}>
        <div className={styles.filters}>
          <form data-admin-search-shell role="search" onSubmit={submitSearch} className={`${styles.search} flex h-11 min-w-0 items-center gap-2 rounded-xl border border-border bg-background px-3`}>
            <Search size={17} className="shrink-0 text-muted" />
            <input value={query} maxLength={100} onChange={(event) => setQuery(event.target.value)} aria-label="Search workspaces" placeholder="Search workspace or organization" className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
            <button type="submit" className="min-h-10 shrink-0 rounded-lg px-2 text-[13px] font-semibold text-brand-contrast hover:bg-brand-soft">Search</button>
          </form>
          <label className={styles.filterLabel}><span>Ownership</span><select value={scope} onChange={(event) => { setLoading(true); setPage(1); setScope(event.target.value as AdminWorkspaceScope); }}>
            <option value="all">All workspaces</option><option value="personal">Personal</option><option value="organization">Organization</option>
          </select></label>
          <label className={styles.filterLabel}><span>Sort by</span><select value={sort} onChange={(event) => { setLoading(true); setPage(1); setSort(event.target.value as AdminWorkspaceSort); }}>
            {sorts.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select></label>
        </div>
      </div>
      {loading ? <p role="status" className="p-10 text-center text-sm text-muted">Loading workspaces…</p> : error ? <div className="flex flex-wrap items-center gap-3 p-5"><p role="alert" className="text-sm text-danger">{error}</p><Button variant="secondary" size="sm" onClick={refresh}>Try again</Button></div> : <div className="overflow-x-auto">
        <table className={`${styles.table} min-w-[960px]`}>
          <colgroup><col className="w-[28%]" /><col className="w-[22%]" /><col className="w-[12%]" /><col className="w-[23%]" /><col className="w-[15%]" /></colgroup>
          <thead><tr><th scope="col">Workspace</th><th scope="col">Ownership</th><th scope="col" className="text-right">Members</th><th scope="col">Assigned roles</th><th scope="col">Created by</th></tr></thead>
          <tbody>{result?.results.map((workspace) => <tr key={workspace.id}>
            <td><p className="truncate font-semibold" title={workspace.name}>{workspace.name}</p><p className="mt-1 text-xs text-muted">Created {new Date(workspace.created_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}</p></td>
            <td><p className="truncate" title={workspace.organization ?? undefined}>{workspace.scope === "organization" ? workspace.organization || "Organization" : "Personal workspace"}</p><p className="mt-1 text-xs text-muted">{workspace.scope === "organization" ? "Organization-owned" : "User-owned"}</p></td>
            <td className="text-right font-medium tabular-nums">{workspace.member_count}</td>
            <td><div className="flex flex-wrap gap-x-3 gap-y-1 text-[13px] text-muted"><span>{workspace.role_counts.admin} Admin</span><span>{workspace.role_counts.editor} Editor</span><span>{workspace.role_counts.viewer} Viewer</span></div></td>
            <td><span className="block truncate" title={workspace.created_by ?? undefined}>{workspace.created_by || "—"}</span></td>
          </tr>)}</tbody>
        </table>
        {result?.results.length === 0 && <p className="px-5 py-10 text-center text-sm text-muted">No workspaces match your filters.</p>}
      </div>}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-4 text-[13px]">
        <span className="text-muted">Page {page} of {totalPages}</span>
        <div className="flex gap-2"><Button size="sm" variant="secondary" disabled={loading || page <= 1} onClick={() => changePage(page - 1)}>Previous</Button><Button size="sm" variant="secondary" disabled={loading || page >= totalPages} onClick={() => changePage(page + 1)}>Next</Button></div>
      </div>
    </section>
    <p className="text-xs leading-5 text-muted">Member counts include active workspace assignments. Organization owners and admins with inherited access are not included.</p>
  </div>;
}
