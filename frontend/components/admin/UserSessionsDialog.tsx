"use client";

import { useEffect, useState } from "react";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";
import {
  getAdminUserSessions,
  revokeAdminUserSession,
  type AdminSession,
  type AdminSessionPage,
  type AdminUser,
} from "@/lib/admin-user-service";

function formatTime(value: string) {
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? "Unknown" : time.toLocaleString();
}

export default function UserSessionsDialog({ user, onClose }: {
  user: AdminUser;
  onClose: () => void;
}) {
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<AdminSessionPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [target, setTarget] = useState<AdminSession | null>(null);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [actionError, setActionError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getAdminUserSessions(user.id, page, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setError("");
        setLoading(false);
        if (page > 1 && result.count <= (page - 1) * result.page_size) setPage((current) => Math.max(1, current - 1));
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : "Could not load sessions.");
        setData(null);
        setLoading(false);
      });
    return () => controller.abort();
  }, [user.id, page, revision]);

  const totalPages = Math.max(1, Math.ceil((data?.count ?? 0) / (data?.page_size || 20)));

  async function confirmRevoke() {
    if (!target || pending || reason.trim().length < 8 || reason.trim().length > 500) return;
    setPending(true);
    setActionError("");
    try {
      await revokeAdminUserSession(target.id, reason);
      setTarget(null);
      setReason("");
      setLoading(true);
      setRevision((current) => current + 1);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Could not revoke session.");
    } finally {
      setPending(false);
    }
  }

  function closeTarget() {
    if (pending) return;
    setTarget(null);
    setReason("");
    setActionError("");
  }

  return <>
    <Dialog open title={`Sessions · ${user.username}`} description="Observed sessions only. An unexpired session is not proof that a user is currently online." onClose={onClose} closeDisabled={pending} className="w-[min(calc(100%_-_2rem),46rem)]">
      <div className="space-y-4">
        {loading && <p role="status" className="text-sm text-muted">Loading observed sessions…</p>}
        {error && <div className="space-y-3"><p role="alert" className="text-sm text-danger">{error}</p><Button size="sm" variant="secondary" onClick={() => { setLoading(true); setError(""); setRevision((value) => value + 1); }}>Retry sessions</Button></div>}
        {!loading && !error && <>
          {data?.results.length ? <div className="space-y-3">
            {data.results.map((session) => <div key={session.id} className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-border p-3">
              <div className="min-w-0 space-y-1 text-xs text-muted">
                <p className="break-words font-medium text-foreground">{session.user_agent || "Unknown client"}</p>
                <p>Last observed: {formatTime(session.last_seen_at)}</p>
                <p>Expires: {formatTime(session.expires_at)}</p>
              </div>
              {session.can_revoke && <Button size="sm" variant="secondary" disabled={pending} onClick={() => { setTarget(session); setReason(""); setActionError(""); }}>Revoke</Button>}
            </div>)}
          </div> : <p className="text-sm text-muted">No tracked sessions for this user.</p>}
          {data?.tracking_note && <p className="text-xs leading-5 text-muted">{data.tracking_note}</p>}
          <div className="flex items-center justify-between text-xs text-muted">
            <span>{data?.count ?? 0} observed sessions · Page {page} of {totalPages}</span>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => { setPage((n) => n - 1); setLoading(true); }}>Previous</Button>
              <Button size="sm" variant="secondary" disabled={page >= totalPages} onClick={() => { setPage((n) => n + 1); setLoading(true); }}>Next</Button>
            </div>
          </div>
        </>}
      </div>
    </Dialog>
    <Dialog open={target !== null} title="Revoke observed session?" description="The user will be signed out on the selected session. The action is recorded in the platform audit log." onClose={closeTarget} closeDisabled={pending}>
      <div className="space-y-4">
        <label className="block text-xs font-semibold">Reason (8–500 characters)
          <textarea disabled={pending} className="mt-2 min-h-24 w-full rounded-xl border border-border bg-background p-3 text-sm font-normal" maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} />
        </label>
        {actionError && <p role="alert" className="text-sm text-danger">{actionError}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" disabled={pending} onClick={closeTarget}>Cancel</Button>
          <Button variant="destructive" loading={pending} disabled={reason.trim().length < 8} onClick={() => void confirmRevoke()}>Revoke session</Button>
        </div>
      </div>
    </Dialog>
  </>;
}
