"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import DashboardShell from "@/components/layout/DashboardShell";
import ShareManagementDialog from "@/components/drive/ShareManagementDialog";
import Button from "@/components/ui/Button";
import { listDirectShares, type SharePage, type ShareTarget } from "@/lib/share-service";
import { WORKSPACE_CHANGED_EVENT } from "@/lib/workspace-context";

export default function SharedByMePage() {
  const [data, setData] = useState<SharePage | null>(null);
  const [page, setPage] = useState(1);
  const [target, setTarget] = useState<ShareTarget | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  const load = useCallback(async (nextPage: number) => {
    const currentId = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const next = await listDirectShares(nextPage);
      if (requestId.current !== currentId) return;
      setData(next);
      setPage(nextPage);
    } catch (exc) {
      if (requestId.current === currentId) setError(exc instanceof Error ? exc.message : "Could not load shared items.");
    } finally {
      if (requestId.current === currentId) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load(1); }, 0);
    function changed() {
      setTarget(null);
      setData(null);
      void load(1);
    }
    window.addEventListener(WORKSPACE_CHANGED_EVENT, changed);
    return () => {
      requestId.current += 1;
      window.clearTimeout(timer);
      window.removeEventListener(WORKSPACE_CHANGED_EVENT, changed);
    };
  }, [load]);

  return (
    <DashboardShell>
      <section className="mx-auto max-w-6xl space-y-5 px-5 py-7 sm:px-8">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Shared by me</h1>
          <p className="mt-1 text-sm text-muted">Direct grants you own in the selected Workspace. Workspace membership permissions are managed separately.</p>
        </div>
        {error && <p role="alert" className="rounded-xl border border-danger/40 px-4 py-3 text-sm text-danger">{error} <Button size="sm" variant="ghost" onClick={() => { void load(page); }}>Retry</Button></p>}
        {loading && <p role="status" className="text-sm text-muted">Loading shared items…</p>}
        {!loading && data?.items.length === 0 && <p className="rounded-xl border border-border bg-surface px-5 py-8 text-sm text-muted">No direct shares in this Workspace.</p>}
        {data && data.items.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-border bg-surface">
            <table className="min-w-full divide-y divide-border text-left text-sm">
              <thead className="bg-background text-xs font-semibold text-muted"><tr>
                <th scope="col" className="px-4 py-3">Item</th>
                <th scope="col" className="px-4 py-3">Recipient</th>
                <th scope="col" className="px-4 py-3">Permission</th>
                <th scope="col" className="px-4 py-3">Shared</th>
                <th scope="col" className="px-4 py-3">Actions</th>
              </tr></thead>
              <tbody className="divide-y divide-border">
                {data.items.map((share) => <tr key={share.id}>
                  <td className="max-w-60 px-4 py-3"><div className="truncate font-medium">{share.item.name}</div><div className="text-xs text-muted">{share.item.kind}</div></td>
                  <td className="max-w-60 truncate px-4 py-3">{share.recipient.email || share.recipient.username}</td>
                  <td className="px-4 py-3 capitalize">{share.permission}</td>
                  <td className="px-4 py-3 text-muted">{new Date(share.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-3"><Button size="sm" variant="secondary" onClick={() => setTarget(share.item)}>Manage</Button></td>
                </tr>)}
              </tbody>
            </table>
          </div>
        )}
        {data && data.pages > 1 && (
          <div className="flex items-center justify-between gap-3 text-sm text-muted">
            <span>Page {page} of {data.pages} · {data.total} grants</span>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" disabled={loading || page <= 1} onClick={() => { void load(page - 1); }}>Previous</Button>
              <Button variant="secondary" size="sm" disabled={loading || page >= data.pages} onClick={() => { void load(page + 1); }}>Next</Button>
            </div>
          </div>
        )}
        <ShareManagementDialog target={target} onClose={() => setTarget(null)} onChanged={() => { void load(page); }} />
      </section>
    </DashboardShell>
  );
}
