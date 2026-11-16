"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { ArrowLeft, Clock3, Copy, RefreshCw, Trash2 } from "lucide-react";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import {
  changeWorkspaceMemberRole,
  createWorkspaceInvite,
  getWorkspaceMembersPage,
  revokeWorkspaceMember,
  type InviteRole,
  type WorkspaceMember,
  type WorkspaceMembersResult,
  type WorkspaceRole,
} from "@/lib/workspace-service";
import { canModifyWorkspaceMember, isWorkspaceRole } from "@/lib/workspace-member-policy";
import { WORKSPACES_UPDATED_EVENT } from "@/lib/workspace-context";
import { drivePath } from "@/lib/drive-paths";

type PendingAction =
  | { kind: "role"; member: WorkspaceMember; role: WorkspaceRole }
  | { kind: "revoke"; member: WorkspaceMember };

function displayError(error: unknown): string {
  return error instanceof Error ? error.message : "The operation could not be completed.";
}

export default function WorkspaceMembersPage({ workspaceId }: { workspaceId: string }) {
  const [result, setResult] = useState<WorkspaceMembersResult | null>(null);
  const [page, setPage] = useState(1);
  const [refreshCount, setRefreshCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [saving, setSaving] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<InviteRole>("viewer");
  const [inviteUrl, setInviteUrl] = useState("");
  const [inviting, setInviting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Delay state updates from an effect so navigation can cancel stale requests.
    const timer = window.setTimeout(() => { if (!cancelled) { setLoading(true); setError(null); } }, 0);
    void getWorkspaceMembersPage(workspaceId, page)
      .then((data) => { if (!cancelled) setResult(data); })
      .catch((reason: unknown) => { if (!cancelled) { setResult(null); setError(displayError(reason)); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [workspaceId, page, refreshCount]);


  async function confirmMutation() {
    if (!pending || saving) return;
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      if (pending.kind === "role") {
        const response = await changeWorkspaceMemberRole(workspaceId, pending.member.assignmentId, pending.role);
        setSuccess(response.changed ? "Member role updated." : "The member already has that role.");
      } else {
        await revokeWorkspaceMember(workspaceId, pending.member.assignmentId);
        setSuccess("Workspace access revoked.");
      }
      setPending(null);
      setRefreshCount((value) => value + 1);
      window.dispatchEvent(new Event(WORKSPACES_UPDATED_EVENT));
    } catch (reason) {
      setError(displayError(reason));
      setPending(null);
    } finally {
      setSaving(false);
    }
  }

  async function createInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inviting) return;
    setInviting(true);
    setError(null);
    setInviteUrl("");
    try {
      const invite = await createWorkspaceInvite(workspaceId, { email: inviteEmail.trim(), role: inviteRole });
      const link = new URL("/workspace-invite", window.location.origin);
      link.searchParams.set("token", invite.inviteToken);
      setInviteUrl(link.toString());
      setSuccess("Invitation created. Copy the link and send it to the recipient.");
    } catch (reason) {
      setError(displayError(reason));
    } finally {
      setInviting(false);
    }
  }

  // Never render a cached list from a different workspace or pagination page.
  const visibleResult = result?.workspaceId === workspaceId && result.page === page ? result : null;

  const description = pending?.kind === "role"
    ? `Change ${pending.member.username}'s role from ${pending.member.workspaceRole} to ${pending.role}?`
    : pending ? `Remove ${pending.member.username} from this workspace? They will lose access unless another permission still grants it.` : "";

  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
      <Link href={drivePath(workspaceId)} className="inline-flex min-h-10 items-center gap-2 rounded-lg text-sm font-medium text-muted hover:text-foreground"><ArrowLeft size={16} /> Back to workspace files</Link>
      <div className="mt-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="wrap-break-word text-2xl font-semibold tracking-tight text-foreground">Members{visibleResult ? ` · ${visibleResult.workspaceName}` : ""}</h1>
          <p className="mt-1 text-sm text-muted">Manage Workspace roles independently from organization and direct file shares.</p>
        </div>
        <div className="flex items-center gap-2">
          <Link href={`/drive/workspaces/${encodeURIComponent(workspaceId)}/activity`} className="ui-control inline-flex h-10 items-center gap-2 rounded-xl border border-border bg-surface px-3 text-[13px] font-semibold text-foreground hover:bg-background"><Clock3 size={14} /> Activity log</Link>
          <button type="button" disabled={loading} onClick={() => setRefreshCount((v) => v + 1)} className="ui-control inline-flex h-10 items-center gap-2 rounded-xl border border-border bg-surface px-3 text-[13px] font-semibold text-foreground hover:bg-background disabled:opacity-50"><RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh</button>
        </div>
      </div>
      {error && <p role="alert" className="mt-4 rounded-xl border border-danger p-3 text-sm text-danger">{error}</p>}
      {success && <p role="status" className="mt-4 text-sm text-foreground">{success}</p>}

      <div className="mt-6 overflow-hidden rounded-2xl border border-border bg-surface">
        <div className="border-b border-border px-5 py-4"><h2 className="text-sm font-semibold text-foreground">Workspace members{visibleResult ? ` (${visibleResult.total})` : ""}</h2></div>
        {loading ? <p className="p-8 text-center text-sm text-muted">Loading members…</p> : !visibleResult ? <p className="p-8 text-center text-sm text-muted">Unable to load members.</p> : visibleResult.members.length === 0 ? <p className="p-8 text-center text-sm text-muted">No active members on this page.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-160 table-fixed text-left text-sm">
              <colgroup><col className="w-[50%]" /><col className="w-[32%]" /><col className="w-[18%]" /></colgroup>
              <thead className="border-b border-border bg-background text-xs text-muted"><tr><th className="px-5 py-3 font-medium">Member</th><th className="px-5 py-3 font-medium">Role</th><th className="px-5 py-3 text-right font-medium">Action</th></tr></thead>
              <tbody className="divide-y divide-border">{visibleResult.members.map((member) => {
                const editable = canModifyWorkspaceMember(member);
                return (
                  <tr key={member.assignmentId}>
                    <td className="px-5 py-3"><div className="truncate font-semibold text-foreground" title={member.username}>{member.username}{member.isSelf ? " (You)" : ""}</div><div className="mt-1 truncate text-xs text-muted" title={member.email}>{member.email}</div></td>
                    <td className="px-5 py-3">
                      <select aria-label={`Role for ${member.username}`} value={member.workspaceRole} disabled={!editable || saving} onChange={(e) => { const role = e.currentTarget.value; if (isWorkspaceRole(role) && role !== member.workspaceRole) setPending({ kind: "role", member, role }); }} className="ui-control h-10 rounded-lg border border-border bg-background px-2 text-xs text-foreground disabled:opacity-60">
                        <option value="viewer">Viewer</option><option value="editor">Editor</option><option value="admin">Admin</option>
                      </select>
                      {member.isProtected && <p className="mt-1 text-[11px] text-muted">Managed by organization</p>}
                    </td>
                    <td className="px-5 py-3 text-right"><button type="button" disabled={!editable || saving} title={editable ? "Revoke workspace membership" : "Cannot modify your own or an organization administrator's membership"} aria-label={`Remove ${member.username}`} onClick={() => setPending({ kind: "revoke", member })} className="ui-control inline-flex h-10 w-9 items-center justify-center rounded-lg text-muted hover:bg-background hover:text-danger disabled:opacity-30"><Trash2 size={16} /></button></td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        )}
        {visibleResult && visibleResult.total > visibleResult.pageSize && <div className="flex items-center justify-between border-t border-border px-5 py-3 text-xs text-muted"><span>Page {page} · {visibleResult.total} members</span><div className="flex gap-2"><Button variant="secondary" disabled={page === 1 || loading} onClick={() => setPage((n) => Math.max(1, n - 1))}>Previous</Button><Button variant="secondary" disabled={!visibleResult.hasNext || loading} onClick={() => setPage((n) => n + 1)}>Next</Button></div></div>}
      </div>

      <div className="mt-6 rounded-2xl border border-border bg-surface p-5">
        <h2 className="text-sm font-semibold text-foreground">Invite a member</h2>
        <p className="mt-1 text-xs text-muted">Invitations are email-bound, expire after seven days and require an existing or registered account to accept.</p>
        <form onSubmit={(event) => { void createInvite(event); }} className="mt-4 flex flex-wrap items-end gap-3">
          <label className="min-w-55 flex-1 space-y-1.5"><span className="block text-xs font-semibold text-foreground">Email address</span><input required type="email" maxLength={254} value={inviteEmail} onChange={(e) => setInviteEmail(e.currentTarget.value)} className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm text-foreground outline-none focus:border-brand" placeholder="colleague@example.com" /></label>
          <label className="space-y-1.5"><span className="block text-xs font-semibold text-foreground">Initial role</span><select value={inviteRole} onChange={(e) => setInviteRole(e.currentTarget.value as InviteRole)} className="h-10 rounded-xl border border-border bg-background px-3 text-sm text-foreground"><option value="viewer">Viewer</option><option value="editor">Editor</option></select></label>
          <Button type="submit" loading={inviting} disabled={inviting || !inviteEmail.trim()}>Create invitation</Button>
        </form>
        {inviteUrl && <div className="mt-4 flex flex-wrap gap-2"><input aria-label="Invitation link" readOnly value={inviteUrl} onFocus={(e) => e.currentTarget.select()} className="h-10 min-w-50 flex-1 rounded-lg border border-border bg-background px-3 text-xs text-foreground" /><Button variant="secondary" onClick={() => { void navigator.clipboard.writeText(inviteUrl).catch(() => setError("Copy failed. Select and copy the link manually.")); }}><Copy size={14} /> Copy link</Button></div>}
      </div>
      <ConfirmDialog open={pending !== null} title={pending?.kind === "role" ? "Confirm role change" : "Remove workspace member"} description={description} confirmLabel={pending?.kind === "role" ? "Change role" : "Remove member"} destructive={pending?.kind === "revoke"} pending={saving} onConfirm={() => { void confirmMutation(); }} onClose={() => { if (!saving) setPending(null); }} />
    </section>
  );
}
