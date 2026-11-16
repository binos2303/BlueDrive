"use client";

import { useEffect, useState, type FormEvent } from "react";
import { RefreshCw, Search } from "lucide-react";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import Button from "@/components/ui/Button";
import { requestAccountApi } from "@/lib/account-service";
import styles from "./AdminDirectory.module.css";

type Organization = { id: string; name: string; status: string; workspaces: number; created_at: string };
type Directory = { count: number; page: number; page_size: number; results: Organization[] };

export default function AdminResourceDirectory() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<Directory | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

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
  const totalPages = Math.max(1, Math.ceil((data?.count ?? 0) / (data?.page_size || 20)));

  return <div className="space-y-6">
    <AdminPageHeader title="Organization Management" description="View organizations and their active collaboration workspaces."
      actions={<Button size="sm" variant="secondary" disabled={loading} onClick={refresh}><RefreshCw size={16} className={loading ? "animate-spin" : ""} />Refresh</Button>} />
    <section className="overflow-hidden rounded-2xl border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4"><h2 className="text-sm font-semibold">Organizations <span className="ml-2 font-normal tabular-nums text-muted">{loading ? "Loading…" : data?.count ?? "Unavailable"}</span></h2><span className="text-xs text-muted">Newest first</span></div>
      <form data-admin-search-shell role="search" onSubmit={submitSearch} className="m-5 flex h-11 min-w-0 items-center gap-3 rounded-xl border border-border bg-background px-3">
        <Search size={17} className="shrink-0 text-muted" /><input value={query} maxLength={100} onChange={(event) => setQuery(event.target.value)} aria-label="Search organizations" placeholder="Search organization name" className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
        <button type="submit" className="min-h-10 shrink-0 rounded-lg px-2 text-[13px] font-semibold text-brand-contrast hover:bg-brand-soft">Search</button>
      </form>
      {loading ? <p className="p-10 text-center text-sm text-muted" role="status">Loading organizations…</p> : error ? <div className="flex flex-wrap items-center gap-3 p-5"><p role="alert" className="text-sm text-danger">{error}</p><Button size="sm" variant="secondary" onClick={refresh}>Try again</Button></div> : <div className="overflow-x-auto">
        <table className={`${styles.table} min-w-[720px]`}>
          <colgroup><col className="w-[40%]" /><col className="w-[18%]" /><col className="w-[18%]" /><col className="w-[24%]" /></colgroup>
          <thead><tr><th scope="col">Name</th><th scope="col" className="text-right">Workspaces</th><th scope="col">Status</th><th scope="col">Created</th></tr></thead>
          <tbody>{data?.results.map((item) => <tr key={item.id}><td><span className="block truncate font-semibold" title={item.name}>{item.name}</span></td><td className="text-right tabular-nums">{item.workspaces}</td><td className="capitalize">{item.status.replace(/_/g, " ")}</td><td className="text-muted">{new Date(item.created_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}</td></tr>)}</tbody>
        </table>
        {data?.results.length === 0 && <p className="p-10 text-center text-sm text-muted">No organizations match your search.</p>}
      </div>}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-4 text-[13px]"><span className="text-muted">Page {page} of {totalPages}</span><div className="flex gap-2"><Button size="sm" variant="secondary" disabled={page <= 1 || loading} onClick={() => { setPage((value) => value - 1); setLoading(true); }}>Previous</Button><Button size="sm" variant="secondary" disabled={page >= totalPages || loading} onClick={() => { setPage((value) => value + 1); setLoading(true); }}>Next</Button></div></div>
    </section>
  </div>;
}
