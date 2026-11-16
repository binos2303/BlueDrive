"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Dialog from "@/components/ui/Dialog";
import { WORKSPACE_CHANGED_EVENT } from "@/lib/workspace-context";
import {
  grantDirectShare, listDirectShares, revokeDirectShare, updateDirectShare,
  type DirectShare, type SharePage, type SharePermission, type ShareTarget,
} from "@/lib/share-service";

type Props = {
  target: ShareTarget | null;
  onClose: () => void;
  onChanged?: () => void;
};

function ShareManagementContent({ target, onClose, onChanged }: Props & { target: ShareTarget }) {
  const [data, setData] = useState<SharePage | null>(null);
  const [page, setPage] = useState(1);
  const [email, setEmail] = useState("");
  const [permission, setPermission] = useState<SharePermission>("viewer");
  const [pending, setPending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [toRevoke, setToRevoke] = useState<DirectShare | null>(null);

  const load = useCallback(async (nextPage: number) => {
    setLoading(true);
    setError(null);
    try {
      const response = await listDirectShares(nextPage, target);
      setData(response);
      setPage(nextPage);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not load sharing permissions.");
    } finally {
      setLoading(false);
    }
  }, [target]);

  useEffect(() => {
    // Delay requests after mount; a request can still finish after closing,
    // but it can only update this unmounted instance, never a different item.
    const timer = window.setTimeout(() => { void load(1); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    window.addEventListener(WORKSPACE_CHANGED_EVENT, onClose);
    return () => window.removeEventListener(WORKSPACE_CHANGED_EVENT, onClose);
  }, [onClose]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || pending || !data?.can_manage) return;
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const result = await grantDirectShare(target, email.trim(), permission);
      setEmail("");
      setNotice(result.detail);
      await load(1);
      onChanged?.();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not share this item.");
    } finally {
      setPending(false);
    }
  }

  async function changePermission(share: DirectShare, next: SharePermission) {
    if (pending || next === share.permission) return;
    setPending(true);
    setNotice(null);
    setError(null);
    try {
      const result = await updateDirectShare(share.id, next);
      setNotice(result.detail);
      await load(page);
      onChanged?.();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not update access.");
    } finally {
      setPending(false);
    }
  }

  async function confirmRevoke() {
    const share = toRevoke;
    if (!share || pending) return;
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      await revokeDirectShare(share.id);
      setToRevoke(null);
      setNotice(`Access revoked for ${share.recipient.email || share.recipient.username}.`);
      await load(Math.max(1, page > 1 && data?.items.length === 1 ? page - 1 : page));
      onChanged?.();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not revoke access.");
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <Dialog open title={`Manage access — ${target.name}`} onClose={() => { if (!pending) onClose(); }} className="w-[min(calc(100%_-_2rem),42rem)]">
        <div className="space-y-5">
          {error && <p role="alert" className="rounded-lg border border-danger/40 px-3 py-2 text-sm text-danger">{error}</p>}
          {notice && <p role="status" className="text-sm text-foreground">{notice}</p>}
          <section aria-label="People with direct access" className="space-y-2">
            <h3 className="text-sm font-semibold">People with direct access</h3>
            <p className="text-xs text-muted">Workspace members and inherited folder permissions are managed separately. Revoking a direct grant may not remove other access.</p>
            {loading && <p role="status" className="text-sm text-muted">Loading sharing permissions…</p>}
            {!loading && data?.items.length === 0 && <p className="text-sm text-muted">No direct shares yet.</p>}
            <div className="divide-y divide-border rounded-lg border border-border">
              {data?.items.map((share) => (
                <div key={share.id} className="flex flex-wrap items-center gap-3 px-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-foreground">{share.recipient.email || share.recipient.username}</p>
                    <p className="truncate text-xs text-muted">{share.recipient.username}</p>
                  </div>
                  <select
                    aria-label={`Permission for ${share.recipient.username}`}
                    className="h-9 rounded-lg border border-border bg-surface px-2 text-xs text-foreground"
                    value={share.permission}
                    disabled={pending || !data.can_manage}
                    onChange={(event) => { void changePermission(share, event.target.value as SharePermission); }}
                  >
                    <option value="viewer">Viewer</option>
                    <option value="editor">Editor</option>
                  </select>
                  <Button size="sm" variant="ghost" disabled={pending || !data.can_manage} onClick={() => setToRevoke(share)}>Revoke</Button>
                </div>
              ))}
            </div>
            {data && data.pages > 1 && <div className="flex items-center justify-between text-xs text-muted">
              <span>Page {data.page} of {data.pages} · {data.total} shares</span>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" disabled={pending || loading || page <= 1} onClick={() => { void load(page - 1); }}>Previous</Button>
                <Button size="sm" variant="secondary" disabled={pending || loading || page >= data.pages} onClick={() => { void load(page + 1); }}>Next</Button>
              </div>
            </div>}
          </section>
          {data?.can_manage && <form onSubmit={(event) => { void submit(event); }} className="space-y-3 border-t border-border pt-4">
            <h3 className="text-sm font-semibold">Grant direct access</h3>
            <label className="block text-xs font-medium text-foreground">Recipient email
              <input type="email" required maxLength={254} autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)}
                disabled={pending} placeholder="name@example.com" className="mt-1.5 h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground" />
            </label>
            <label className="block text-xs font-medium text-foreground">Permission
              <select value={permission} disabled={pending} onChange={(event) => setPermission(event.target.value as SharePermission)}
                className="mt-1.5 h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground">
                <option value="viewer">Viewer — can view and download</option>
                <option value="editor">Editor — can modify items</option>
              </select>
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={onClose} disabled={pending}>Close</Button>
              <Button type="submit" loading={pending} disabled={pending || !email.trim()}>Share</Button>
            </div>
          </form>}
          {!data?.can_manage && <div className="flex justify-end"><Button variant="secondary" onClick={onClose}>Close</Button></div>}
        </div>
      </Dialog>
      <ConfirmDialog open={toRevoke !== null} title="Revoke direct access?" destructive
        description={`Remove direct access for ${toRevoke?.recipient.email || toRevoke?.recipient.username || "this user"}? Other Workspace or inherited permissions may still apply.`}
        confirmLabel="Revoke access" pending={pending} onClose={() => { if (!pending) setToRevoke(null); }} onConfirm={() => { void confirmRevoke(); }} />
    </>
  );
}

export default function ShareManagementDialog({ target, onClose, onChanged }: Props) {
  if (!target) return null;
  return <ShareManagementContent key={`${target.kind}:${target.id}`} target={target} onClose={onClose} onChanged={onChanged} />;
}
