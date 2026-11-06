"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { RefreshCw, Search } from "lucide-react";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import Button from "@/components/ui/Button";
import { getAdminTeams, type AdminTeamPage } from "@/lib/admin-teams-service";
import { type AdminTeamScope, type AdminTeamSort } from "@/lib/admin-teams-query";

const SORTS: Array<{ value: AdminTeamSort; label: string }> = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "name_asc", label: "Name A–Z" },
  { value: "name_desc", label: "Name Z–A" },
];

export default function AdminTeamDirectory() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState<AdminTeamScope>("all");
  const [sort, setSort] = useState<AdminTeamSort>("newest");
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [result, setResult] = useState<AdminTeamPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getAdminTeams({ query: search, scope, sort, page }, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setResult(data);
        setError("");
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setResult(null);
        setError(reason instanceof Error ? reason.message : "Unable to load workspace teams.");
        setLoading(false);
      });
    return () => controller.abort();
  }, [search, scope, sort, page, reload]);

  function searchTeams(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setPage(1);
    setSearch(query.trim());
    setReload((value) => value + 1);
  }

  function changePage(nextPage: number) {
    setLoading(true);
    setPage(nextPage);
  }

  const totalPages = Math.max(1, Math.ceil((result?.count ?? 0) / (result?.page_size || 20)));
  return <div className="space-y-5">
    <AdminPageHeader
      title="Teams Management"
      actions={<Button size="sm" variant="secondary" disabled={loading} onClick={() => {
        setLoading(true);
        setReload((value) => value + 1);
      }}><RefreshCw size={15} className={loading ? "animate-spin" : ""} /> Refresh</Button>}
    />

    <div className="rounded-[20px] border border-border bg-surface px-5 py-4 text-[13px] leading-6 text-muted">
      Teams are represented by existing active Workspaces. Member counts include only current, explicit
      Workspace assignments; Tenant Owners/Admins with inherited access and direct file shares are not counted.
      Workspace membership and invitations are managed by an authorized Workspace manager, not by Platform Admin.
      <Link href="/admin/workspaces" className="ml-1 font-semibold text-brand-contrast hover:underline">Browse workspaces</Link>
    </div>

    <section className="overflow-hidden rounded-[20px] border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
        <div>
          <p className="text-xs text-muted">Matching teams</p>
          <p className="text-[25px] font-semibold">{loading ? "—" : result?.count ?? "—"}</p>
        </div>
        <span className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted">Read-only platform directory</span>
      </div>
      <div className="grid gap-3 border-b border-border p-4 lg:grid-cols-[minmax(230px,2fr)_minmax(150px,1fr)_minmax(160px,1fr)]">
        <form role="search" onSubmit={searchTeams} className="flex h-11 min-w-0 items-center gap-2 rounded-xl border border-border bg-background px-3">
          <Search size={15} className="shrink-0 text-muted" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search teams" placeholder="Search team or organization" className="min-w-0 flex-1 bg-transparent text-[13px] outline-none" />
          <button type="submit" className="text-xs font-semibold text-brand-contrast">Search</button>
        </form>
        <label className="flex flex-col gap-1 text-[11px] font-medium text-muted">
          <span>Workspace scope</span>
          <select value={scope} onChange={(event) => {
            setLoading(true);
            setPage(1);
            setScope(event.target.value as AdminTeamScope);
          }} className="h-11 rounded-xl border border-border bg-background px-3 text-[12px] text-foreground">
            <option value="all">All scopes</option>
            <option value="personal">Personal workspaces</option>
            <option value="organization">Organization workspaces</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px] font-medium text-muted">
          <span>Sort by</span>
          <select value={sort} onChange={(event) => {
            setLoading(true);
            setPage(1);
            setSort(event.target.value as AdminTeamSort);
          }} className="h-11 rounded-xl border border-border bg-background px-3 text-[12px] text-foreground">
            {SORTS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
      </div>

      {loading && <p role="status" className="p-8 text-center text-sm text-muted">Loading teams…</p>}
      {!loading && error && <p role="alert" className="p-5 text-sm text-danger">{error}</p>}
      {!loading && !error && <div className="overflow-x-auto">
        <table className="w-full min-w-[780px] text-left text-[13px]">
          <thead className="bg-background text-[11px] font-semibold text-muted">
            <tr>
              <th scope="col" className="px-5 py-3">TEAM (WORKSPACE)</th>
              <th scope="col" className="px-4 py-3">SCOPE / ORGANIZATION</th>
              <th scope="col" className="px-4 py-3">CREATED BY</th>
              <th scope="col" className="px-4 py-3">ASSIGNED MEMBERS</th>
              <th scope="col" className="px-4 py-3">ROLES</th>
            </tr>
          </thead>
          <tbody>{result?.results.map((team) => <tr key={team.id} className="border-t border-border/70">
            <td className="px-5 py-4 font-semibold">{team.name}</td>
            <td className="px-4 py-4 text-muted">{team.scope === "organization" ? team.organization || "Organization" : "Personal workspace"}</td>
            <td className="px-4 py-4 text-muted">{team.created_by || "—"}</td>
            <td className="px-4 py-4 font-medium">{team.member_count}</td>
            <td className="px-4 py-4 text-xs text-muted">{team.role_counts.admin} Admin · {team.role_counts.editor} Editor · {team.role_counts.viewer} Viewer</td>
          </tr>)}</tbody>
        </table>
        {result?.results.length === 0 && <p className="p-8 text-center text-sm text-muted">No matching active workspace teams.</p>}
      </div>}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-4 text-xs">
        <span className="text-muted">Page {page} of {totalPages}</span>
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" disabled={loading || page <= 1} onClick={() => changePage(page - 1)}>Previous</Button>
          <Button size="sm" variant="secondary" disabled={loading || page >= totalPages} onClick={() => changePage(page + 1)}>Next</Button>
        </div>
      </div>
    </section>
  </div>;
}
