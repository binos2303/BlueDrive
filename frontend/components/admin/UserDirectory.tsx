"use client";

import { useEffect, useState } from "react";
import { Search, RefreshCw } from "lucide-react";

type User = { id: string | number; username: string; email: string; is_active: boolean; is_staff: boolean; last_login: string | null };
type Directory = { count: number; page: number; page_size: number; results: User[] };
const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

export default function UserDirectory() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<Directory | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiBase}/accounts/api/admin/users/?page=${page}&q=${encodeURIComponent(search)}`, { credentials: "include", cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 403 ? "Administrator access denied." : `Unable to load users (HTTP ${response.status}).`);
        return response.json() as Promise<Directory>;
      })
      .then((result) => { setData(result); setError(""); setLoading(false); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : "Unable to load users."); setLoading(false); } });
    return () => controller.abort();
  }, [page, search, refresh]);
  const totalPages = Math.max(1, Math.ceil((data?.count ?? 0) / (data?.page_size || 20)));
  return <div className="space-y-5">
    <div><p className="text-xs text-muted">Management / Users</p><h1 className="mt-1 text-2xl font-semibold">User Management</h1><p className="mt-2 text-sm text-muted">Live Django accounts · Read-only directory</p></div>
    <section className="rounded-2xl border border-border bg-surface p-5"><p className="text-sm text-muted">Total matching users</p><p className="mt-2 text-3xl font-semibold">{data?.count ?? "—"}</p></section>
    <section className="overflow-hidden rounded-2xl border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-border p-4">
        <form className="flex flex-1 items-center gap-2 rounded-xl border border-border bg-background px-3 py-2" onSubmit={(event) => { event.preventDefault(); setPage(1); setSearch(query.trim()); }}><Search size={16} className="text-muted"/><input aria-label="Search users" className="min-w-0 flex-1 bg-transparent text-sm outline-none" placeholder="Search username or email" value={query} onChange={(event) => setQuery(event.target.value)}/><button type="submit" className="text-sm font-medium text-brand">Search</button></form>
        <button type="button" onClick={() => { setLoading(true); setRefresh((n) => n + 1); }} className="flex items-center gap-2 rounded-xl border border-border px-3 py-2 text-sm"><RefreshCw size={15}/>Refresh</button>
      </div>
      {error && <p role="alert" className="p-5 text-sm text-red-600">{error}</p>}
      {loading ? <p className="p-8 text-center text-sm text-muted">Loading users…</p> : !error && <div className="overflow-x-auto"><table className="w-full min-w-[620px] text-left text-sm"><thead className="bg-background text-xs text-muted"><tr><th className="px-5 py-3">Username</th><th className="px-5 py-3">Email</th><th className="px-5 py-3">Role</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Last login</th></tr></thead><tbody>{data?.results.map((user) => <tr key={user.id} className="border-t border-border"><td className="px-5 py-3 font-medium">{user.username}</td><td className="px-5 py-3">{user.email || "—"}</td><td className="px-5 py-3">{user.is_staff ? "Staff" : "User"}</td><td className="px-5 py-3">{user.is_active ? "Active" : "Inactive"}</td><td className="px-5 py-3">{user.last_login ? new Date(user.last_login).toLocaleString() : "Never"}</td></tr>)}</tbody></table>{data?.results.length === 0 && <p className="p-8 text-center text-sm text-muted">No users found.</p>}</div>}
      <div className="flex items-center justify-between border-t border-border p-4 text-sm"><span className="text-muted">Page {page} of {totalPages}</span><div className="flex gap-2"><button disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Previous</button><button disabled={page >= totalPages || loading} onClick={() => setPage((p) => p + 1)} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Next</button></div></div>
    </section>
    <p className="text-xs text-muted">Account suspension and role changes are not exposed until platform audit logging and session revocation are implemented.</p>
  </div>;
}
