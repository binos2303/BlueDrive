"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Building2, FolderKanban, Plus, RefreshCw, Users } from "lucide-react";
import { useAccount } from "@/components/account/AccountProvider";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import DataTable from "@/components/ui/DataTable";
import Dialog from "@/components/ui/Dialog";
import Input from "@/components/ui/Input";
import { AccountServiceError } from "@/lib/account-service";
import {
  addWorkspaceMember,
  createWorkspace,
  getOrganizationAdminData,
  getWorkspaceMembers,
  getWorkspaceRemovalRequests,
  decideWorkspaceRemoval,
  inviteOrganizationMember,
  manageOrganizationMember,
  removeWorkspaceMember,
  updateWorkspace,
  type OrganizationMember,
  type OrganizationAccountCapabilities,
  type WorkspaceMemberAssignment,
  type WorkspaceRemovalRequests,
} from "@/lib/organization-admin-service";
import type { OrganizationWorkspace, WorkspaceRemovalRequest } from "@/lib/workspace-service";
import { isWorkspaceRole } from "@/lib/workspace-member-policy";
import { WORKSPACES_UPDATED_EVENT } from "@/lib/workspace-context";
import { finiteQuotaBytes } from "@/lib/organization-account-policy";

type AdminTab = "workspaces" | "members" | "requests";
type WorkspaceRole = WorkspaceMemberAssignment["workspaceRole"];
const roles: WorkspaceRole[] = ["viewer", "editor", "admin"];
const inputClass = "min-h-10 w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm text-foreground";
const tableCellClass = "border-t border-border px-4 py-3 text-sm";

function errorMessage(error: unknown): string {
  if (error instanceof AccountServiceError) return error.message;
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function formatRole(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/** Organization members and workspaces have direct, per-user permissions only. */
export default function OrganizationAdminPage() {
  const { state } = useAccount();
  const snapshot = state.status === "loaded" ? state.account : null;
  const tenant = snapshot?.account.tenant ?? null;
  const tenantId = tenant?.id ?? null;
  const isBusiness = snapshot?.account.type === "business";
  const canManage = Boolean(tenant && isBusiness && ["owner", "admin"].includes(tenant.role));

  const [tab, setTab] = useState<AdminTab>("workspaces");
  const [workspaces, setWorkspaces] = useState<OrganizationWorkspace[]>([]);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<OrganizationAccountCapabilities>({ inviteAccounts: false, manageAccounts: false });
  const [memberFormOpen, setMemberFormOpen] = useState(false);
  const [memberForm, setMemberForm] = useState({ username: "", email: "", quota: "0", reason: "" });
  const [memberError, setMemberError] = useState<string | null>(null);
  const [memberFieldErrors, setMemberFieldErrors] = useState<Record<string, string[]>>({});
  const [memberAction, setMemberAction] = useState<{ member: OrganizationMember; action: "suspend" | "restore" | "reinvite" } | null>(null);
  const [memberReason, setMemberReason] = useState("");
  const memberMutation = useRef(false);
  const memberAttempt = useRef<{ payload: string; key: string } | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<OrganizationWorkspace | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [archiveTarget, setArchiveTarget] = useState<OrganizationWorkspace | null>(null);

  const [selectedWorkspace, setSelectedWorkspace] = useState<OrganizationWorkspace | null>(null);
  const [assignments, setAssignments] = useState<WorkspaceMemberAssignment[]>([]);
  const [accessLoading, setAccessLoading] = useState(false);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [selectedMemberId, setSelectedMemberId] = useState("");
  const [selectedRole, setSelectedRole] = useState<WorkspaceRole>("viewer");
  const accessRequestId = useRef(0);
  const [pendingMemberChange, setPendingMemberChange] = useState<{
    workspaceId: string;
    member: WorkspaceMemberAssignment;
    role?: WorkspaceRole;
  } | null>(null);
  const [removalPage, setRemovalPage] = useState(1);
  const [removalRefresh, setRemovalRefresh] = useState(0);
  const [removalList, setRemovalList] = useState<{ tenantId: string; data: WorkspaceRemovalRequests } | null>(null);
  const [removalLoading, setRemovalLoading] = useState(true);
  const [removalError, setRemovalError] = useState<string | null>(null);
  const [removalAction, setRemovalAction] = useState<{ tenantId: string; request: WorkspaceRemovalRequest; decision: "approve" | "reject" } | null>(null);
  const [removalReason, setRemovalReason] = useState("");
  const decidingRemoval = useRef(false);

  const activeMembers = useMemo(() => members.filter((member) => member.status === "active"), [members]);
  const assignedIds = new Set(assignments.filter((item) => item.status === "active").map((item) => item.membershipId));
  const availableMembers = activeMembers.filter((member) => !assignedIds.has(member.membershipId));
  const visibleRemovals = removalList?.tenantId === tenantId && removalList.data.page === removalPage ? removalList.data : null;

  useEffect(() => {
    if (tab !== "requests" || !canManage || !tenantId) return;
    let active = true;
    void Promise.resolve().then(() => { if (active) { setRemovalLoading(true); setRemovalError(null); } });
    void getWorkspaceRemovalRequests(tenantId, removalPage)
      .then((data) => { if (active) setRemovalList({ tenantId, data }); })
      .catch((cause: unknown) => { if (active) { setRemovalList(null); setRemovalError(errorMessage(cause)); } })
      .finally(() => { if (active) setRemovalLoading(false); });
    return () => { active = false; };
  }, [tab, canManage, tenantId, removalPage, removalRefresh]);

  useEffect(() => () => { accessRequestId.current += 1; }, [tenantId]);

  const load = useCallback(async () => {
    if (!tenantId) return;
    setLoading(true);
    try {
      const data = await getOrganizationAdminData(tenantId);
      setWorkspaces(data.workspaces);
      setMembers(data.members);
      setCapabilities(data.capabilities);
      setError(null);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    if (!canManage || !tenantId) return;

    // Ignore responses from an organization that is no longer selected.
    let active = true;
    void getOrganizationAdminData(tenantId)
      .then((data) => {
        if (!active) return;
        setWorkspaces(data.workspaces);
        setMembers(data.members);
        setCapabilities(data.capabilities);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (active) setError(errorMessage(cause));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [canManage, tenantId]);

  const refreshAccess = useCallback(async (workspace: OrganizationWorkspace) => {
    if (!tenantId) return;
    const requestId = ++accessRequestId.current;
    setAccessLoading(true);
    setAccessError(null);
    try {
      const result = await getWorkspaceMembers(tenantId, workspace.id);
      if (requestId !== accessRequestId.current) return;
      setAssignments(result.members);
      setAccessError(null);
    } catch (cause) {
      if (requestId !== accessRequestId.current) return;
      setAccessError(errorMessage(cause));
      throw cause;
    } finally {
      if (requestId === accessRequestId.current) setAccessLoading(false);
    }
  }, [tenantId]);

  async function perform(action: () => Promise<unknown>, success: string, refreshWorkspace?: OrganizationWorkspace) {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      if (refreshWorkspace) {
        await refreshAccess(refreshWorkspace);
      } else {
        await load();
      }
      setNotice(success);
      return true;
    } catch (cause) {
      if (refreshWorkspace) setAccessError(errorMessage(cause));
      else setError(errorMessage(cause));
      return false;
    } finally {
      setSaving(false);
    }
  }

  function openForm(workspace?: OrganizationWorkspace) {
    setError(null);
    setEditing(workspace ?? null);
    setName(workspace?.name ?? "");
    setDescription(workspace?.description ?? "");
    setFormOpen(true);
  }

  async function saveWorkspace() {
    if (!tenantId || !name.trim()) return;
    const success = await perform(
      () => editing
        ? updateWorkspace(tenantId, editing.id, { name: name.trim(), description: description.trim() })
        : createWorkspace(tenantId, { name: name.trim(), description: description.trim() }),
      editing ? "Workspace updated." : "Workspace created.",
    );
    if (success) {
      setFormOpen(false);
      window.dispatchEvent(new Event(WORKSPACES_UPDATED_EVENT));
    }
  }

  async function toggleArchive() {
    if (!tenantId || !archiveTarget) return;
    const nextStatus = archiveTarget.status === "active" ? "archived" : "active";
    const success = await perform(
      () => updateWorkspace(tenantId, archiveTarget.id, { status: nextStatus }),
      `Workspace ${nextStatus === "archived" ? "archived" : "restored"}.`,
    );
    if (success) {
      setArchiveTarget(null);
      window.dispatchEvent(new Event(WORKSPACES_UPDATED_EVENT));
    }
  }

  function openAccess(workspace: OrganizationWorkspace) {
    setSelectedWorkspace(workspace);
    setAssignments([]);
    setAccessError(null);
    setSelectedMemberId("");
    void refreshAccess(workspace).catch(() => undefined);
  }

  function closeAccess() {
    accessRequestId.current += 1;
    setSelectedWorkspace(null);
    setPendingMemberChange(null);
  }

  async function grantMember(membershipId: string, role: WorkspaceRole) {
    if (!tenantId || !selectedWorkspace) return;
    const success = await perform(
      () => addWorkspaceMember(tenantId, selectedWorkspace.id, { membership_id: membershipId, role }),
      "Workspace access updated.", selectedWorkspace,
    );
    if (success) setSelectedMemberId("");
    return success;
  }

  async function revokeMember(membershipId: string) {
    if (!tenantId || !selectedWorkspace) return;
    return perform(
      () => removeWorkspaceMember(tenantId, selectedWorkspace.id, membershipId),
      "Workspace access removed.", selectedWorkspace,
    );
  }

  async function confirmMemberChange() {
    if (!pendingMemberChange || saving || selectedWorkspace?.id !== pendingMemberChange.workspaceId) return;
    const { member, role } = pendingMemberChange;
    const success = role
      ? await grantMember(member.membershipId, role)
      : await revokeMember(member.membershipId);
    if (success) setPendingMemberChange(null);
  }

  function openMemberForm() {
    setMemberForm({ username: "", email: "", quota: "0", reason: "" }); setMemberError(null);
    setMemberFieldErrors({}); memberAttempt.current = null; setMemberFormOpen(true);
  }

  async function inviteMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenantId || !capabilities.inviteAccounts || memberMutation.current) return;
    memberMutation.current = true; setSaving(true); setMemberError(null); setMemberFieldErrors({});
    try {
      const input = { username: memberForm.username.trim(), email: memberForm.email.trim(),
        limit_bytes: finiteQuotaBytes(memberForm.quota), reason: memberForm.reason.trim() };
      const payload = `${tenantId}:${JSON.stringify(input)}`;
      // Retry cùng tenant và payload giữ key để không tạo nhân viên trùng.
      if (memberAttempt.current?.payload !== payload) memberAttempt.current = { payload, key: crypto.randomUUID() };
      const result = await inviteOrganizationMember(tenantId, input, memberAttempt.current.key);
      setMemberFormOpen(false); memberAttempt.current = null;
      await load();
      setNotice(`Employee invitation sent.${result.storageReady ? "" : " Storage is not ready; uploads remain unavailable."}`);
    } catch (cause) {
      setMemberError(errorMessage(cause));
      if (cause instanceof AccountServiceError) setMemberFieldErrors(cause.fieldErrors);
    } finally { memberMutation.current = false; setSaving(false); }
  }

  async function changeMember(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!tenantId || !memberAction || memberMutation.current) return;
    if (memberAction.action === "reinvite" ? !capabilities.inviteAccounts : !capabilities.manageAccounts) return;
    memberMutation.current = true; setSaving(true); setMemberError(null);
    try {
      await manageOrganizationMember(tenantId, memberAction.member.membershipId, memberAction.action, memberReason.trim());
      setNotice(memberAction.action === "reinvite" ? "Invitation sent. Previous invitation links are no longer valid."
        : memberAction.action === "suspend" ? "Membership suspended." : "Membership restored.");
      setMemberAction(null); await load();
    } catch (cause) { setMemberError(errorMessage(cause)); }
    finally { memberMutation.current = false; setSaving(false); }
  }

  function openMemberAction(member: OrganizationMember, action: "suspend" | "restore" | "reinvite") {
    setMemberAction({ member, action }); setMemberReason(""); setMemberError(null);
  }

  async function decideRemoval(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenantId || removalAction?.tenantId !== tenantId || decidingRemoval.current || removalReason.trim().length < 8) return;
    const requestId = accessRequestId.current;
    decidingRemoval.current = true; setSaving(true); setRemovalError(null);
    try {
      await decideWorkspaceRemoval(tenantId, removalAction.request.id, removalAction.decision, removalReason.trim());
      if (requestId !== accessRequestId.current) return;
      setNotice(removalAction.decision === "approve" ? "Removal approved and workspace access revoked." : "Removal request rejected. Workspace access is unchanged.");
      setRemovalAction(null); setRemovalPage(1); setRemovalRefresh((value) => value + 1);
      window.dispatchEvent(new Event(WORKSPACES_UPDATED_EVENT));
    } catch (cause) { setRemovalError(errorMessage(cause)); }
    finally { decidingRemoval.current = false; setSaving(false); }
  }

  if (state.status === "loading") return <div className="p-8 text-muted">Loading account…</div>;
  if (!isBusiness || !tenant) {
    return <div className="p-8 text-muted">Select a business organization to manage workspaces.</div>;
  }
  if (!canManage) {
    return <div className="p-8 text-danger">Organization administrator access is required.</div>;
  }

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-5 p-4 sm:p-6 xl:p-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted"><Building2 size={15} /> Organization</p>
          <h1 className="mt-2 text-2xl font-semibold">{tenant.name}</h1>
          <p className="mt-1 text-sm text-muted">Manage workspaces and grant access to individual members.</p>
        </div>
        <Button variant="secondary" loading={tab === "requests" ? removalLoading : loading} onClick={() => tab === "requests" ? setRemovalRefresh((value) => value + 1) : void load()}><RefreshCw size={16} /> Refresh</Button>
      </header>

      {error && !formOpen && !archiveTarget && <p role="alert" className="rounded-xl border border-danger/30 p-3 text-sm text-danger">{error}</p>}
      {notice && <p role="status" className="rounded-xl border border-border p-3 text-sm">{notice}</p>}

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4"><p className="text-sm text-muted">Active workspaces</p><p className="mt-2 text-2xl font-semibold">{workspaces.filter((item) => item.status === "active").length}</p></div>
        <div className="rounded-xl border border-border bg-surface p-4"><p className="text-sm text-muted">Active members</p><p className="mt-2 text-2xl font-semibold">{activeMembers.length}</p></div>
      </div>

      <section className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <Button variant={tab === "workspaces" ? "primary" : "ghost"} size="sm" onClick={() => setTab("workspaces")}><FolderKanban size={15} /> Workspaces</Button>
          <Button variant={tab === "members" ? "primary" : "ghost"} size="sm" onClick={() => setTab("members")}><Users size={15} /> Members</Button>
          <Button variant={tab === "requests" ? "primary" : "ghost"} size="sm" onClick={() => setTab("requests")}>Removal requests</Button>
          <div className="flex-1" />
          {tab === "workspaces" && <Button size="sm" onClick={() => openForm()}><Plus size={15} /> New workspace</Button>}
          {tab === "members" && capabilities.inviteAccounts && <Button size="sm" disabled={saving} onClick={openMemberForm}><Plus size={15} /> Invite employee</Button>}
        </div>

        {tab === "requests" ? <div className="p-4 sm:p-5">
          <h2 className="text-base font-semibold">Workspace removal requests</h2>
          <p className="mt-1 text-sm text-muted">Review the current membership before approving. A requester cannot decide their own request.</p>
          {removalError && !removalAction && <p role="alert" className="mt-4 text-sm text-danger">{removalError}</p>}
          {removalLoading ? <p className="mt-5 text-sm text-muted">Loading removal requests…</p> : !visibleRemovals ? <p className="mt-5 text-sm text-muted">Unable to load requests. <button type="button" onClick={() => setRemovalRefresh((value) => value + 1)} className="ui-control rounded text-brand-contrast underline">Retry</button></p> : visibleRemovals.requests.length === 0 ? <p className="mt-5 text-sm text-muted">No removal requests.</p> : <ul className="mt-4 divide-y divide-border">{visibleRemovals.requests.map((request) => <li key={request.id} className="flex flex-wrap items-start justify-between gap-3 py-4">
            <div className="min-w-0 flex-1"><p className="wrap-break-word text-sm font-semibold">{request.targetUsername} · {request.workspaceName}</p><p className="mt-1 wrap-break-word text-sm text-muted">Requested by {request.requestedByUsername}: {request.reason}</p><p className="mt-1 text-xs capitalize text-muted">{request.status}</p></div>
            {request.status === "pending" && <div className="flex gap-2">{(["approve", "reject"] as const).map((decision) => <Button key={decision} variant={decision === "approve" ? "primary" : "secondary"} size="sm" disabled={saving || request.requestedByUsername === snapshot?.profile.username} onClick={() => { setRemovalAction({ tenantId: tenant.id, request, decision }); setRemovalReason(""); setRemovalError(null); }}>{decision === "approve" ? "Approve" : "Reject"}</Button>)}</div>}
          </li>)}</ul>}
          {visibleRemovals && (visibleRemovals.count > visibleRemovals.pageSize || removalPage > 1) && <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4"><span className="text-xs text-muted">Page {removalPage} · {visibleRemovals.count} requests</span><div className="flex gap-2"><Button variant="secondary" disabled={removalLoading || removalPage === 1} onClick={() => setRemovalPage((value) => value - 1)}>Previous</Button><Button variant="secondary" disabled={removalLoading || !visibleRemovals.hasNext} onClick={() => setRemovalPage((value) => value + 1)}>Next</Button></div></div>}
        </div> : loading ? <p className="p-6 text-sm text-muted">Loading organization data…</p> : tab === "workspaces" ? (
          <DataTable>
            <thead><tr className="text-xs text-muted"><th className="p-3">Workspace</th><th className="p-3">Members</th><th className="p-3">Status</th><th className="p-3">Actions</th></tr></thead>
            <tbody>{workspaces.map((workspace) => (
              <tr key={workspace.id}>
                <td className={tableCellClass}><strong>{workspace.name}</strong>{workspace.isDefault && <span className="ml-2 text-xs text-muted">Default</span>}<p className="text-xs text-muted">{workspace.description}</p></td>
                <td className={tableCellClass}>{workspace.memberCount}</td>
                <td className={tableCellClass}>{formatRole(workspace.status)}</td>
                <td className={tableCellClass}><div className="flex flex-wrap gap-1">
                  <Button variant="ghost" size="sm" onClick={() => openAccess(workspace)}>Access</Button>
                  <Button variant="ghost" size="sm" onClick={() => openForm(workspace)}>Edit</Button>
                  <Button variant="ghost" size="sm" disabled={workspace.isDefault && workspace.status === "active"} onClick={() => { setError(null); setArchiveTarget(workspace); }}>{workspace.status === "active" ? "Archive" : "Restore"}</Button>
                </div></td>
              </tr>
            ))}</tbody>
          </DataTable>
        ) : (
          <DataTable>
            <thead><tr className="text-xs text-muted"><th className="p-3">Member</th><th className="p-3">Organization role</th><th className="p-3">Status</th>{(capabilities.inviteAccounts || capabilities.manageAccounts) && <th className="p-3">Actions</th>}</tr></thead>
            <tbody>{members.map((member) => (
              <tr key={member.membershipId}><td className={tableCellClass}>{member.username}<p className="text-xs text-muted">{member.email}</p></td><td className={tableCellClass}>{formatRole(member.role)}</td><td className={tableCellClass}>{formatRole(member.status)}</td>
                {(capabilities.inviteAccounts || capabilities.manageAccounts) && <td className={tableCellClass}>{member.managed && member.role === "member" && <div className="flex flex-wrap gap-2">
                  {member.status === "invited" && capabilities.inviteAccounts && <Button variant="secondary" size="sm" disabled={saving} onClick={() => openMemberAction(member, "reinvite")}>Resend invitation</Button>}
                  {member.status === "active" && capabilities.manageAccounts && <Button variant="ghost" size="sm" disabled={saving} onClick={() => openMemberAction(member, "suspend")}>Suspend</Button>}
                  {member.status === "suspended" && capabilities.manageAccounts && <Button variant="secondary" size="sm" disabled={saving} onClick={() => openMemberAction(member, "restore")}>Restore</Button>}
                </div>}</td>}
              </tr>
            ))}</tbody>
          </DataTable>
        )}
      </section>

      <Dialog open={removalAction?.tenantId === tenantId} title={removalAction?.decision === "approve" ? "Approve member removal" : "Reject removal request"} description={removalAction ? `${removalAction.request.targetUsername} · ${removalAction.request.workspaceName}` : undefined} onClose={() => setRemovalAction(null)} closeDisabled={saving}>
        <form className="space-y-4" onSubmit={(event) => void decideRemoval(event)}>
          {removalError && <p role="alert" className="text-sm text-danger">{removalError}</p>}
          <p className="text-sm text-muted">{removalAction?.decision === "approve" ? "Approval immediately revokes this Workspace assignment. Organization membership and stored data are retained." : "Rejection closes this request and keeps the existing Workspace assignment."}</p>
          <label className="block text-sm font-medium">Decision reason<textarea required minLength={8} maxLength={500} value={removalReason} disabled={saving} onChange={(event) => setRemovalReason(event.target.value)} className="mt-2 min-h-24 w-full rounded-xl border border-border bg-background p-3 text-sm" /></label>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={saving} onClick={() => setRemovalAction(null)}>Cancel</Button><Button type="submit" loading={saving} disabled={removalReason.trim().length < 8}>{removalAction?.decision === "approve" ? "Approve removal" : "Reject request"}</Button></div>
        </form>
      </Dialog>

      <Dialog open={formOpen} title={editing ? "Edit workspace" : "Create workspace"} onClose={() => setFormOpen(false)} closeDisabled={saving}>
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void saveWorkspace(); }}>
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <label className="block text-sm">Name<input className={`${inputClass} mt-1`} value={name} maxLength={255} required onChange={(event) => setName(event.target.value)} /></label>
          <label className="block text-sm">Description<textarea className={`${inputClass} mt-1`} value={description} maxLength={4000} rows={3} onChange={(event) => setDescription(event.target.value)} /></label>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={saving} onClick={() => setFormOpen(false)}>Cancel</Button><Button type="submit" loading={saving} disabled={!name.trim()}>Save</Button></div>
        </form>
      </Dialog>

      <Dialog open={memberFormOpen} title="Invite employee" description="Create an organization-owned account. The employee sets their own password using an emailed invitation." onClose={() => setMemberFormOpen(false)} closeDisabled={saving}>
        <form className="space-y-4" onSubmit={(event) => void inviteMember(event)}>
          {memberError && <p role="alert" className="text-sm text-danger">{memberError}</p>}
          {([['username', 'Username', 'text', 'username'], ['email', 'Email', 'email', 'email'], ['quota', 'My Drive storage limit (GiB)', 'number', 'limit_bytes']] as const).map(([key, label, type, errorKey]) => <div key={key}>
            <label htmlFor={`employee-${key}`} className="block text-sm font-medium">{label}</label>
            <Input id={`employee-${key}`} required className="mt-1" type={type} min={type === 'number' ? 0 : undefined} step={type === 'number' ? 1 : undefined} maxLength={type === 'email' ? 254 : 150} autoComplete={key === 'email' ? 'email' : key === 'username' ? 'username' : 'off'} disabled={saving} value={memberForm[key]} invalid={Boolean(memberFieldErrors[errorKey])} aria-describedby={memberFieldErrors[errorKey] ? `employee-${key}-error` : undefined} onChange={(event) => setMemberForm({ ...memberForm, [key]: event.target.value })} />
            {memberFieldErrors[errorKey] && <p id={`employee-${key}-error`} className="mt-1 text-xs text-danger">{memberFieldErrors[errorKey].join(' ')}</p>}
          </div>)}
          <p className="text-xs leading-5 text-muted">My Drive belongs to this organization and is private to the employee. 0 blocks uploads until storage is allocated.</p>
          <label className="block text-sm font-medium">Reason<textarea required minLength={8} maxLength={500} value={memberForm.reason} disabled={saving} onChange={(event) => setMemberForm({ ...memberForm, reason: event.target.value })} className="mt-1 min-h-20 w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm" /></label>
          {memberFieldErrors.reason && <p className="text-xs text-danger">{memberFieldErrors.reason.join(' ')}</p>}
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={saving} onClick={() => setMemberFormOpen(false)}>Cancel</Button><Button type="submit" loading={saving} disabled={memberForm.reason.trim().length < 8}>Send invitation</Button></div>
        </form>
      </Dialog>
      <Dialog open={memberAction?.action === 'reinvite'} title="Resend employee invitation" description={`${memberAction?.member.username ?? 'Employee'} · ${tenant.name}`} onClose={() => setMemberAction(null)} closeDisabled={saving}>
        <form className="space-y-4" onSubmit={(event) => void changeMember(event)}>
          {memberError && <p role="alert" className="text-sm text-danger">{memberError}</p>}
          <p className="text-sm text-muted">Send a fresh invitation. Previous invitation links will stop working.</p>
          <label className="block text-sm font-medium">Reason<textarea required minLength={8} maxLength={500} value={memberReason} disabled={saving} onChange={(event) => setMemberReason(event.target.value)} className="mt-1 min-h-20 w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm" /></label>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={saving} onClick={() => setMemberAction(null)}>Cancel</Button><Button type="submit" loading={saving} disabled={memberReason.trim().length < 8}>Send invitation</Button></div>
        </form>
      </Dialog>
      <ConfirmDialog open={Boolean(memberAction && memberAction.action !== 'reinvite')}
        title={memberAction?.action === 'suspend' ? 'Suspend employee' : 'Restore employee'}
        description={memberAction?.action === 'suspend' ? `Suspend ${memberAction.member.username}'s organization access?` : `Restore ${memberAction?.member.username ?? 'this employee'}'s organization membership?`}
        confirmLabel={memberAction?.action === 'suspend' ? 'Suspend employee' : 'Restore employee'}
        destructive={memberAction?.action === 'suspend'} pending={saving} error={memberError}
        onClose={() => setMemberAction(null)} onConfirm={() => void changeMember()} />

      <Dialog open={Boolean(selectedWorkspace)} title={selectedWorkspace ? `${selectedWorkspace.name} members` : "Workspace access"} description="Assign access directly to organization members." onClose={closeAccess} closeDisabled={saving} className="w-[min(calc(100%_-_2rem),50rem)]">
        {selectedWorkspace && <div className="space-y-4">
          {accessError && <p role="alert" className="text-sm text-danger">{accessError}</p>}
          <form className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_8rem_auto]" onSubmit={(event) => { event.preventDefault(); if (selectedMemberId) void grantMember(selectedMemberId, selectedRole); }}>
            <select aria-label="Organization member" className={`${inputClass} flex-1`} value={selectedMemberId} onChange={(event) => setSelectedMemberId(event.target.value)} disabled={saving || selectedWorkspace.status !== "active"}>
              <option value="">Select a member…</option>
              {availableMembers.map((member) => <option key={member.membershipId} value={member.membershipId}>{member.username} ({member.email})</option>)}
            </select>
            <select aria-label="Workspace role" className={inputClass} value={selectedRole} onChange={(event) => setSelectedRole(event.target.value as WorkspaceRole)} disabled={saving || selectedWorkspace.status !== "active"}>
              {roles.map((role) => <option key={role} value={role}>{formatRole(role)}</option>)}
            </select>
            <Button type="submit" loading={saving} disabled={!selectedMemberId || selectedWorkspace.status !== "active"}>Add member</Button>
          </form>
          {accessLoading ? <p className="text-sm text-muted">Loading members…</p> : (
            <DataTable>
              <thead><tr className="text-xs text-muted"><th className="p-3">Member</th><th className="p-3">Role</th><th className="p-3">Action</th></tr></thead>
              <tbody>{assignments.filter((item) => item.status === "active").map((member) => (
                <tr key={member.assignmentId}>
                  <td className={tableCellClass}>{member.username}<p className="text-xs text-muted">{member.email}</p></td>
                  <td className={tableCellClass}>
                    <select aria-label={`Role for ${member.username}`} className={inputClass} value={member.workspaceRole} disabled={saving || selectedWorkspace.status !== "active"} onChange={(event) => {
                      const role = event.target.value;
                      if (isWorkspaceRole(role) && role !== member.workspaceRole) {
                        setAccessError(null);
                        setPendingMemberChange({ workspaceId: selectedWorkspace.id, member, role });
                      }
                    }}>
                      {roles.map((role) => <option key={role} value={role}>{formatRole(role)}</option>)}
                    </select>
                  </td>
                  <td className={tableCellClass}><Button variant="ghost" size="sm" disabled={saving || selectedWorkspace.status !== "active"} onClick={() => {
                    setAccessError(null);
                    setPendingMemberChange({ workspaceId: selectedWorkspace.id, member });
                  }}>Remove</Button></td>
                </tr>
              ))}</tbody>
            </DataTable>
          )}
        </div>}
      </Dialog>

      <ConfirmDialog open={pendingMemberChange !== null}
        title={pendingMemberChange?.role ? "Confirm role change" : "Remove workspace member"}
        description={pendingMemberChange?.role
          ? `Change ${pendingMemberChange.member.username}'s role to ${formatRole(pendingMemberChange.role)} in ${selectedWorkspace?.name ?? "this workspace"}?`
          : `Remove ${pendingMemberChange?.member.username ?? "this member"} from ${selectedWorkspace?.name ?? "this workspace"}?`}
        confirmLabel={pendingMemberChange?.role ? "Change role" : "Remove member"}
        destructive={!pendingMemberChange?.role} pending={saving} error={accessError}
        onClose={() => setPendingMemberChange(null)} onConfirm={() => void confirmMemberChange()} />

      <ConfirmDialog open={Boolean(archiveTarget)} title={archiveTarget?.status === "active" ? "Archive workspace" : "Restore workspace"} description={`Change status of “${archiveTarget?.name ?? ""}”?`} destructive={archiveTarget?.status === "active"} pending={saving} error={error} onClose={() => { setArchiveTarget(null); setError(null); }} onConfirm={() => void toggleArchive()} />
    </div>
  );
}
