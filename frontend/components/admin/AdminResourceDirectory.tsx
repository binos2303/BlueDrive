"use client";

import { useEffect, useState, type FormEvent } from "react";
import { RefreshCw, Search } from "lucide-react";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import Button from "@/components/ui/Button";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

type Org = { id: string; name: string; status: string; workspaces: number; created_at: string };
type Workspace = { id: string; name: string; status: string; scope: "organization" | "personal"; organization: string | null; created_at: string };
type ResourceSort = "newest" | "oldest" | "name_asc" | "name_desc";
type Directory<T> = { count: number; page: number; page_size: number; sort?: ResourceSort; results: T[] };

const SORT_OPTIONS: Array<{ value: ResourceSort; label: string }> = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "name_asc", label: "Name A–Z" },
  { value: "name_desc", label: "Name Z–A" },
];

function dateLabel(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function AdminResourceDirectory({ kind }: { kind: "organizations" | "workspaces" }) {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<ResourceSort>("newest");
  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);
  const [data, setData] = useState<Directory<Org | Workspace> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const isOrganizations = kind === "organizations";

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ page: String(page), q: search, sort });
    fetch(`${apiBase}/accounts/api/admin/${kind}/?${params}`, {
      credentials: "include", cache: "no-store", signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) throw new Error(`Unable to load ${kind} (HTTP ${response.status}).`);
      return response.json() as Promise<Directory<Org | Workspace>>;
    }).then((result) => {
      if (!controller.signal.aborted) { setData(result); setError(""); setLoading(false); }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) { setData(null); setError(reason instanceof Error ? reason.message : "Request failed."); setLoading(false); }
    });
    return () => controller.abort();
  }, [kind, page, search, sort, refreshKey]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1); setSearch(query.trim()); setRefreshKey((n) => n + 1); setLoading(true);
  }
  const totalPages = Math.max(1, Math.ceil((data?.count ?? 0) / (data?.page_size || 20)));

  return <div className="space-y-5">
    <AdminPageHeader
      title={isOrganizations ? "Organization Management" : "Workspace Management"}
      actions={
        <Button size="sm" variant="secondary" disabled={loading} onClick={() => { setLoading(true); setRefreshKey((n) => n + 1); }}>
          <RefreshCw size={15} className={loading ? "animate-spin" : ""} />Refresh
        </Button>
      }
    />
    <section className="rounded-[20px] border border-border bg-surface px-5 py-4"><p className="text-[12px] text-muted">{isOrganizations ? "Matching organizations" : "Matching workspaces"}</p><p className="mt-1 text-[26px] font-semibold">{loading ? "—" : (data?.count ?? "—")}</p></section>
    <section className="overflow-hidden rounded-[20px] border border-border bg-surface">
      <div className="border-b border-border p-4">
        <div className="grid items-end gap-3 lg:grid-cols-[minmax(260px,1.8fr)_220px]">
          <form data-admin-search-shell role="search" onSubmit={submitSearch} className="flex h-11 min-w-0 items-center gap-2 rounded-xl border border-border bg-background px-3">
            <Search size={15} className="text-muted" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label={`Search ${kind}`} placeholder={isOrganizations ? "Search organization name" : "Search workspace or owner organization"} className="min-w-0 flex-1 bg-transparent text-[13px] outline-none" />
            <button type="submit" className="text-xs font-semibold text-brand-contrast">Search</button>
          </form>
          <label className="flex min-w-0 flex-col gap-1 text-[11px] font-medium text-muted">
            <span>Sort by</span>
            <select aria-label={`Sort ${kind}`} className="h-11 rounded-xl border border-border bg-background px-3 text-[12px] text-foreground" value={sort} onChange={(event) => { setSort(event.target.value as ResourceSort); setPage(1); setLoading(true); }}>
              {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        </div>
      </div>
      {error && <p role="alert" className="p-5 text-sm text-danger">{error}</p>}
      {loading && <p className="p-8 text-center text-sm text-muted" role="status">Loading {kind}…</p>}
      {!loading && !error && <div className="overflow-x-auto"><table className="w-full min-w-150 text-left text-[13px]"><thead className="bg-background text-[12px] text-muted"><tr><th className="px-5 py-3">Name</th><th className="px-5 py-3">{isOrganizations ? "Workspaces" : "Ownership"}</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Created</th></tr></thead><tbody>{data?.results.map((item) => <tr key={item.id} className="border-t border-border/70"><td className="px-5 py-3 font-semibold">{item.name}</td><td className="px-5 py-3 text-muted">{"workspaces" in item ? item.workspaces : item.scope === "organization" ? (item.organization || "Organization") : "Personal workspace"}</td><td className="px-5 py-3 capitalize">{item.status.replace(/_/g, " ")}</td><td className="px-5 py-3 text-muted">{dateLabel(item.created_at)}</td></tr>)}</tbody></table>{data?.results.length === 0 && <p className="p-8 text-center text-sm text-muted">No matching {kind}.</p>}</div>}
      <div className="flex items-center justify-between border-t border-border p-4 text-xs"><span className="text-muted">Page {page} of {totalPages}</span><div className="flex gap-2"><button type="button" disabled={page <= 1 || loading} onClick={() => { setPage((p) => p - 1); setLoading(true); }} className="rounded-lg border border-border px-3 py-2 disabled:opacity-40">Previous</button><button type="button" disabled={page >= totalPages || loading} onClick={() => { setPage((p) => p + 1); setLoading(true); }} className="rounded-lg border border-border px-3 py-2 disabled:opacity-40">Next</button></div></div>
    </section>
  </div>;
}
