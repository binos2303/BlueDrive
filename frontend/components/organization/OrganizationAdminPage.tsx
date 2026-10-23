"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  Check,
  CircleAlert,
  FolderKanban,
  Layers3,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
  Users,
  UsersRound,
  X,
  type LucideIcon,
} from "lucide-react";
import { useAccount } from "@/components/account/AccountProvider";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import DataTable from "@/components/ui/DataTable";
import Dialog from "@/components/ui/Dialog";
import { AccountServiceError } from "@/lib/account-service";
import {
  addGroupMember,
  addWorkspaceMember,
  createGroup,
  createWorkspace,
  getGroupMembers,
  getOrganizationAdminData,
  getWorkspaceGroupAccess,
  getWorkspaceMembers,
  grantWorkspaceGroup,
  removeGroupMember,
  removeWorkspaceMember,
  revokeWorkspaceGroup as revokeWorkspaceGroupGrant,
  updateGroup,
  updateWorkspace,
  type GroupMemberAssignment,
  type OrganizationGroup,
  type OrganizationMember,
  type WorkspaceGroupGrant,
  type WorkspaceMemberAssignment,
} from "@/lib/organization-admin-service";
import type { OrganizationWorkspace } from "@/lib/workspace-service";
import { WORKSPACES_UPDATED_EVENT } from "@/lib/workspace-context";

type AdminTab = "workspaces" | "groups" | "members";
type StatusAction = {
  kind: "workspace" | "group";
  id: string;
  name: string;
  nextStatus: "active" | "archived";
  isDefault?: boolean;
};

const inputClassName = "mt-1.5 min-h-10 w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm text-foreground outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/10 disabled:cursor-not-allowed disabled:opacity-60";
const labelClassName = "block text-xs font-semibold text-muted";
const tableHeaderClassName = "bg-background text-[11px] font-semibold tracking-wide text-muted";

function messageFromError(error: unknown): string {
  if (error instanceof AccountServiceError) return error.message;
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function statusBadge(status: "active" | "archived" | "suspended" | "invited" | "revoked") {
  if (status === "active") return <Badge variant="success">Active</Badge>;
  if (status === "archived" || status === "revoked") return <Badge variant="neutral">{status === "archived" ? "Archived" : "Revoked"}</Badge>;
  return <Badge variant="warning">{status === "invited" ? "Invited" : "Suspended"}</Badge>;
}

function roleLabel(role: string) {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

export default function OrganizationAdminPage() {
  const { state: accountState } = useAccount();
  const account = accountState.status === "loaded" ? accountState.account : null;
  const tenant = account?.account.tenant ?? null;
  const tenantId = tenant?.id ?? null;
  const isBusiness = account?.account.type === "business";
  const canManage = Boolean(tenant && isBusiness && ["owner", "admin"].includes(tenant.role));

  const [activeTab, setActiveTab] = useState<AdminTab>("workspaces");
  const [workspaces, setWorkspaces] = useState<OrganizationWorkspace[]>([]);
  const [groups, setGroups] = useState<OrganizationGroup[]>([]);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const [workspaceFormOpen, setWorkspaceFormOpen] = useState(false);
  const [editingWorkspace, setEditingWorkspace] = useState<OrganizationWorkspace | null>(null);
  const [workspaceName, setWorkspaceName] = useState("");
  const [workspaceDescription, setWorkspaceDescription] = useState("");

  const [groupFormOpen, setGroupFormOpen] = useState(false);
  const [editingGroup, setEditingGroup] = useState<OrganizationGroup | null>(null);
  const [groupName, setGroupName] = useState("");
  const [groupDescription, setGroupDescription] = useState("");

  const [pendingStatusAction, setPendingStatusAction] = useState<StatusAction | null>(null);

  const [managedWorkspace, setManagedWorkspace] = useState<OrganizationWorkspace | null>(null);
  const [workspaceMembers, setWorkspaceMembers] = useState<WorkspaceMemberAssignment[]>([]);
  const [workspaceGroupGrants, setWorkspaceGroupGrants] = useState<WorkspaceGroupGrant[]>([]);
  const [workspaceRoleDrafts, setWorkspaceRoleDrafts] = useState<Record<string, WorkspaceMemberAssignment["workspaceRole"]>>({});
  const [workspaceGroupRoleDrafts, setWorkspaceGroupRoleDrafts] = useState<Record<string, WorkspaceGroupGrant["role"]>>({});
  const [workspaceAccessLoading, setWorkspaceAccessLoading] = useState(false);
  const [workspaceAccessError, setWorkspaceAccessError] = useState<string | null>(null);
  const [newWorkspaceMemberId, setNewWorkspaceMemberId] = useState("");
  const [newWorkspaceMemberRole, setNewWorkspaceMemberRole] = useState<WorkspaceMemberAssignment["workspaceRole"]>("viewer");
  const [newWorkspaceGroupId, setNewWorkspaceGroupId] = useState("");
  const [newWorkspaceGroupRole, setNewWorkspaceGroupRole] = useState<WorkspaceGroupGrant["role"]>("viewer");

  const [managedGroup, setManagedGroup] = useState<OrganizationGroup | null>(null);
  const [groupMembers, setGroupMembers] = useState<GroupMemberAssignment[]>([]);
  const [groupMembersLoading, setGroupMembersLoading] = useState(false);
  const [groupMembersError, setGroupMembersError] = useState<string | null>(null);
  const [newGroupMemberId, setNewGroupMemberId] = useState("");

  const activeMembers = useMemo(() => members.filter((member) => member.status === "active"), [members]);
  const activeGroups = useMemo(() => groups.filter((group) => group.status === "active"), [groups]);
  const activeWorkspaces = useMemo(() => workspaces.filter((workspace) => workspace.status === "active"), [workspaces]);

  const loadOrganization = useCallback(async (showSpinner = true) => {
    if (!tenantId) return;
    if (showSpinner) setLoading(true);
    setPageError(null);
    try {
      const result = await getOrganizationAdminData(tenantId);
      setWorkspaces(result.workspaces);
      setGroups(result.groups);
      setMembers(result.members);
    } catch (error) {
      setPageError(messageFromError(error));
      throw error;
    } finally {
      if (showSpinner) setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    if (!canManage || !tenantId) return;
    const timer = window.setTimeout(() => {
      void loadOrganization().catch(() => undefined);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [canManage, loadOrganization, tenantId]);

  async function performMutation(action: () => Promise<unknown>, message: string, afterSuccess?: () => void) {
    setSaving(true);
    setPageError(null);
    setSuccessMessage(null);
    try {
      await action();
      await loadOrganization(false);
      afterSuccess?.();
      setSuccessMessage(message);
    } catch (error) {
      setPageError(messageFromError(error));
    } finally {
      setSaving(false);
    }
  }

  function openWorkspaceForm(workspace?: OrganizationWorkspace) {
    setEditingWorkspace(workspace ?? null);
    setWorkspaceName(workspace?.name ?? "");
    setWorkspaceDescription(workspace?.description ?? "");
    setWorkspaceFormOpen(true);
  }

  function openGroupForm(group?: OrganizationGroup) {
    setEditingGroup(group ?? null);
    setGroupName(group?.name ?? "");
    setGroupDescription(group?.description ?? "");
    setGroupFormOpen(true);
  }

  async function saveWorkspace() {
    if (!tenantId || !workspaceName.trim()) return;
    await performMutation(
      () => editingWorkspace
        ? updateWorkspace(tenantId, editingWorkspace.id, { name: workspaceName.trim(), description: workspaceDescription.trim() })
        : createWorkspace(tenantId, { name: workspaceName.trim(), description: workspaceDescription.trim() }),
      editingWorkspace ? "Workspace updated." : "Workspace created.",
      () => {
        setWorkspaceFormOpen(false);
        window.dispatchEvent(new Event(WORKSPACES_UPDATED_EVENT));
      },
    );
  }

  async function saveGroup() {
    if (!tenantId || !groupName.trim()) return;
    await performMutation(
      () => editingGroup
        ? updateGroup(tenantId, editingGroup.id, { name: groupName.trim(), description: groupDescription.trim() })
        : createGroup(tenantId, { name: groupName.trim(), description: groupDescription.trim() }),
      editingGroup ? "Group updated." : "Group created.",
      () => setGroupFormOpen(false),
    );
  }

  async function confirmStatusChange() {
    if (!tenantId || !pendingStatusAction) return;
    const action = pendingStatusAction;
    await performMutation(
      () => action.kind === "workspace"
        ? updateWorkspace(tenantId, action.id, { status: action.nextStatus })
        : updateGroup(tenantId, action.id, { name: action.name, status: action.nextStatus, description: (groups.find((group) => group.id === action.id)?.description ?? "") }),
      `${action.kind === "workspace" ? "Workspace" : "Group"} ${action.nextStatus === "archived" ? "archived" : "restored"}.`,
      () => {
        setPendingStatusAction(null);
        if (action.kind === "workspace") window.dispatchEvent(new Event(WORKSPACES_UPDATED_EVENT));
      },
    );
  }

  async function openWorkspaceAccess(workspace: OrganizationWorkspace) {
    if (!tenantId) return;
    setManagedWorkspace(workspace);
    setWorkspaceMembers([]);
    setWorkspaceGroupGrants([]);
    setWorkspaceRoleDrafts({});
    setWorkspaceGroupRoleDrafts({});
    setWorkspaceAccessError(null);
    setWorkspaceAccessLoading(true);
    setNewWorkspaceMemberId("");
    setNewWorkspaceGroupId("");
    try {
      const [memberResult, groupResult] = await Promise.all([
        getWorkspaceMembers(tenantId, workspace.id),
        getWorkspaceGroupAccess(tenantId, workspace.id),
      ]);
      setWorkspaceMembers(memberResult.members);
      setWorkspaceGroupGrants(groupResult.groupAccess);
      setWorkspaceRoleDrafts(Object.fromEntries(memberResult.members.map((member) => [member.membershipId, member.workspaceRole])));
      setWorkspaceGroupRoleDrafts(Object.fromEntries(groupResult.groupAccess.map((grant) => [grant.groupId, grant.role])));
    } catch (error) {
      setWorkspaceAccessError(messageFromError(error));
    } finally {
      setWorkspaceAccessLoading(false);
    }
  }

  async function refreshWorkspaceAccess(workspace: OrganizationWorkspace) {
    if (!tenantId) return;
    try {
      const [memberResult, groupResult] = await Promise.all([
        getWorkspaceMembers(tenantId, workspace.id),
        getWorkspaceGroupAccess(tenantId, workspace.id),
      ]);
      setWorkspaceMembers(memberResult.members);
      setWorkspaceGroupGrants(groupResult.groupAccess);
      setWorkspaceRoleDrafts(Object.fromEntries(memberResult.members.map((member) => [member.membershipId, member.workspaceRole])));
      setWorkspaceGroupRoleDrafts(Object.fromEntries(groupResult.groupAccess.map((grant) => [grant.groupId, grant.role])));
      await loadOrganization(false);
      setWorkspaceAccessError(null);
    } catch (error) {
      setWorkspaceAccessError(messageFromError(error));
      throw error;
    }
  }

  async function assignWorkspaceMember() {
    if (!tenantId || !managedWorkspace || !newWorkspaceMemberId) return;
    setWorkspaceAccessError(null);
    setSaving(true);
    try {
      await addWorkspaceMember(tenantId, managedWorkspace.id, {
        membership_id: newWorkspaceMemberId,
        role: newWorkspaceMemberRole,
      });
      await refreshWorkspaceAccess(managedWorkspace);
      setNewWorkspaceMemberId("");
      setSuccessMessage("Workspace member access updated.");
    } catch (error) {
      setWorkspaceAccessError(messageFromError(error));
    } finally {
      setSaving(false);
    }
  }

  function changeWorkspaceMemberRole(membershipId: string, role: WorkspaceMemberAssignment["workspaceRole"]) {
    setWorkspaceRoleDrafts((current) => ({ ...current, [membershipId]: role }));
  }

  async function saveWorkspaceMemberRole(membershipId: string) {
    if (!tenantId || !managedWorkspace) return;
    const member = workspaceMembers.find((item) => item.membershipId === membershipId);
    const role = workspaceRoleDrafts[membershipId];
    if (!member || !role || role === member.workspaceRole) return;
    setSaving(true);
    setWorkspaceAccessError(null);
    try {
      await addWorkspaceMember(tenantId, managedWorkspace.id, { membership_id: membershipId, role });
      await refreshWorkspaceAccess(managedWorkspace);
      setSuccessMessage("Workspace role updated.");
    } catch (error) {
      setWorkspaceAccessError(messageFromError(error));
    } finally {
      setSaving(false);
    }
  }

  function changeWorkspaceGroupRole(groupId: string, role: WorkspaceGroupGrant["role"]) {
    setWorkspaceGroupRoleDrafts((current) => ({ ...current, [groupId]: role }));
  }

  async function saveWorkspaceGroupRole(groupId: string) {
    if (!tenantId || !managedWorkspace) return;
    const grant = workspaceGroupGrants.find((item) => item.groupId === groupId);
    const role = workspaceGroupRoleDrafts[groupId];
    if (!grant || !role || role === grant.role) return;
    setSaving(true);
    setWorkspaceAccessError(null);
    try {
      await grantWorkspaceGroup(tenantId, managedWorkspace.id, { group_id: groupId, role });
      await refreshWorkspaceAccess(managedWorkspace);
      setSuccessMessage("Group workspace role updated.");
    } catch (error) {
      setWorkspaceAccessError(messageFromError(error));
    } finally {
      setSaving(false);
    }
  }

  async function revokeWorkspaceMember(membershipId: string) {
    if (!tenantId || !managedWorkspace) return;
    setSaving(true);
    setWorkspaceAccessError(null);
    try {
      await removeWorkspaceMember(tenantId, managedWorkspace.id, membershipId);
      await refreshWorkspaceAccess(managedWorkspace);
      setSuccessMessage("Workspace member access revoked.");
    } catch (error) {
      setWorkspaceAccessError(messageFromError(error));
    } finally {
      setSaving(false);
    }
  }

  async function assignWorkspaceGroup() {
    if (!tenantId || !managedWorkspace || !newWorkspaceGroupId) return;
    setSaving(true);
    setWorkspaceAccessError(null);
    try {
      await grantWorkspaceGroup(tenantId, managedWorkspace.id, {
        group_id: newWorkspaceGroupId,
        role: newWorkspaceGroupRole,
      });
      await refreshWorkspaceAccess(managedWorkspace);
      setNewWorkspaceGroupId("");
      setSuccessMessage("Group workspace access updated.");
    } catch (error) {
      setWorkspaceAccessError(messageFromError(error));
    } finally {
      setSaving(false);
    }
  }

  async function revokeWorkspaceGroup(groupId: string) {
    if (!tenantId || !managedWorkspace) return;
    setSaving(true);
    setWorkspaceAccessError(null);
    try {
      await revokeWorkspaceGroupGrant(tenantId, managedWorkspace.id, groupId);
      await refreshWorkspaceAccess(managedWorkspace);
      setSuccessMessage("Group workspace access revoked.");
    } catch (error) {
      setWorkspaceAccessError(messageFromError(error));
    } finally {
      setSaving(false);
    }
  }

  async function openGroupMembers(group: OrganizationGroup) {
    if (!tenantId) return;
    setManagedGroup(group);
    setGroupMembers([]);
    setGroupMembersError(null);
    setGroupMembersLoading(true);
    setNewGroupMemberId("");
    try {
      const result = await getGroupMembers(tenantId, group.id);
      setGroupMembers(result.members);
    } catch (error) {
      setGroupMembersError(messageFromError(error));
    } finally {
      setGroupMembersLoading(false);
    }
  }

  async function refreshGroupMembers(group: OrganizationGroup) {
    if (!tenantId) return;
    try {
      const result = await getGroupMembers(tenantId, group.id);
      setGroupMembers(result.members);
      await loadOrganization(false);
      setGroupMembersError(null);
    } catch (error) {
      setGroupMembersError(messageFromError(error));
      throw error;
    }
  }

  async function assignGroupMember() {
    if (!tenantId || !managedGroup || !newGroupMemberId) return;
    setSaving(true);
    setGroupMembersError(null);
    try {
      await addGroupMember(tenantId, managedGroup.id, newGroupMemberId);
      await refreshGroupMembers(managedGroup);
      setNewGroupMemberId("");
      setSuccessMessage("Group member added.");
    } catch (error) {
      setGroupMembersError(messageFromError(error));
    } finally {
      setSaving(false);
    }
  }

  async function revokeGroupMember(membershipId: string) {
    if (!tenantId || !managedGroup) return;
    setSaving(true);
    setGroupMembersError(null);
    try {
      await removeGroupMember(tenantId, managedGroup.id, membershipId);
      await refreshGroupMembers(managedGroup);
      setSuccessMessage("Group member removed.");
    } catch (error) {
      setGroupMembersError(messageFromError(error));
    } finally {
      setSaving(false);
    }
  }

  const activeWorkspaceMemberIds = useMemo(
    () => new Set(workspaceMembers.filter((member) => member.status === "active").map((member) => member.membershipId)),
    [workspaceMembers],
  );
  const activeGroupMemberIds = useMemo(() => new Set(groupMembers.map((member) => member.membershipId)), [groupMembers]);
  const grantedGroupIds = useMemo(() => new Set(workspaceGroupGrants.map((grant) => grant.groupId)), [workspaceGroupGrants]);
  const availableWorkspaceMembers = activeMembers.filter((member) => !activeWorkspaceMemberIds.has(member.membershipId));
  const availableGroupMembers = activeMembers.filter((member) => !activeGroupMemberIds.has(member.membershipId));
  const availableWorkspaceGroups = activeGroups.filter((group) => !grantedGroupIds.has(group.id));

  if (accountState.status === "loading") {
    return <PageFrame><LoadingPanel label="Loading account access…" /></PageFrame>;
  }
  if (accountState.status === "error") {
    return <PageFrame><MessagePanel title="Account unavailable" message={accountState.error} variant="error" /></PageFrame>;
  }
  if (!isBusiness) {
    return <PageFrame><MessagePanel title="Organization administration" message="This area is available to business organizations. Personal Drive settings remain in your account area." /></PageFrame>;
  }
  if (!tenant) {
    return <PageFrame><MessagePanel title="Select an organization" message="This account is a member of multiple organizations. Organization selection must be configured before the correct administration scope can be loaded." /></PageFrame>;
  }
  if (!canManage) {
    return <PageFrame><MessagePanel title="Administrator access required" message="Only organization owners and administrators can manage workspaces, groups, and organization membership." variant="error" /></PageFrame>;
  }

  return (
    <PageFrame>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted">
            <Building2 size={14} /> Organization console
          </div>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{tenant.name}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
            Manage workspaces, groups, and access within your organization. Platform infrastructure remains managed separately by the service provider.
          </p>
        </div>
        <Button variant="secondary" onClick={() => void loadOrganization().catch(() => undefined)} loading={loading}>
          <RefreshCw size={15} /> Refresh
        </Button>
      </div>

      {pageError && <InlineMessage message={pageError} variant="error" onClose={() => setPageError(null)} />}
      {successMessage && <InlineMessage message={successMessage} variant="success" onClose={() => setSuccessMessage(null)} />}

      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <MetricCard label="Active workspaces" value={String(activeWorkspaces.length)} hint={`${workspaces.length - activeWorkspaces.length} archived`} icon={FolderKanban} />
        <MetricCard label="Active groups" value={String(activeGroups.length)} hint={`${groups.length - activeGroups.length} archived`} icon={UsersRound} />
        <MetricCard label="Organization members" value={String(activeMembers.length)} hint={`${members.length - activeMembers.length} inactive or invited`} icon={Users} />
      </div>

      <section className="overflow-hidden rounded-2xl border border-border bg-surface">
        <div className="flex flex-wrap items-center gap-1 border-b border-border px-3 py-3 sm:px-5">
          <TabButton active={activeTab === "workspaces"} onClick={() => setActiveTab("workspaces")} icon={<Layers3 size={16} />}>Workspaces</TabButton>
          <TabButton active={activeTab === "groups"} onClick={() => setActiveTab("groups")} icon={<UsersRound size={16} />}>Groups</TabButton>
          <TabButton active={activeTab === "members"} onClick={() => setActiveTab("members")} icon={<Users size={16} />}>Members</TabButton>
          <div className="flex-1" />
          {activeTab === "workspaces" && <Button size="sm" onClick={() => openWorkspaceForm()}><Plus size={14} /> New workspace</Button>}
          {activeTab === "groups" && <Button size="sm" onClick={() => openGroupForm()}><Plus size={14} /> New group</Button>}
        </div>

        {loading ? <LoadingPanel label="Loading organization data…" /> : activeTab === "workspaces" ? (
          <WorkspaceTable
            workspaces={workspaces}
            onEdit={openWorkspaceForm}
            onManage={(workspace) => void openWorkspaceAccess(workspace)}
            onStatusChange={(workspace) => setPendingStatusAction({
              kind: "workspace",
              id: workspace.id,
              name: workspace.name,
              nextStatus: workspace.status === "active" ? "archived" : "active",
              isDefault: workspace.isDefault,
            })}
          />
        ) : activeTab === "groups" ? (
          <GroupTable
            groups={groups}
            onEdit={openGroupForm}
            onManageMembers={(group) => void openGroupMembers(group)}
            onStatusChange={(group) => setPendingStatusAction({
              kind: "group",
              id: group.id,
              name: group.name,
              nextStatus: group.status === "active" ? "archived" : "active",
            })}
          />
        ) : (
          <MembersTable members={members} />
        )}
      </section>

      <div className="mt-4 flex items-start gap-3 rounded-2xl border border-border bg-background p-4 text-sm text-muted">
        <ShieldCheck size={17} className="mt-0.5 shrink-0 text-brand" />
        <p>Membership changes are checked by the backend and recorded in organization activity logs. This console does not expose provider-level MinIO or server controls.</p>
      </div>

      <Dialog
        open={workspaceFormOpen}
        title={editingWorkspace ? "Edit workspace" : "Create workspace"}
        description="A workspace is a collaboration area inside this organization. It does not create a separate storage cluster."
        onClose={() => setWorkspaceFormOpen(false)}
      >
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void saveWorkspace(); }}>
          <label className={labelClassName}>
            Workspace name
            <input autoFocus maxLength={255} value={workspaceName} onChange={(event) => setWorkspaceName(event.currentTarget.value)} required className={inputClassName} placeholder="e.g. Engineering" />
          </label>
          <label className={labelClassName}>
            Description
            <textarea maxLength={4000} rows={3} value={workspaceDescription} onChange={(event) => setWorkspaceDescription(event.currentTarget.value)} className={`${inputClassName} resize-y`} placeholder="What is this workspace used for?" />
          </label>
          <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={() => setWorkspaceFormOpen(false)} disabled={saving}>Cancel</Button>
            <Button type="submit" loading={saving} disabled={!workspaceName.trim()}>{editingWorkspace ? "Save changes" : "Create workspace"}</Button>
          </div>
        </form>
      </Dialog>

      <Dialog
        open={groupFormOpen}
        title={editingGroup ? "Edit group" : "Create group"}
        description="Groups collect organization members so access can be granted collectively to a workspace."
        onClose={() => setGroupFormOpen(false)}
      >
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void saveGroup(); }}>
          <label className={labelClassName}>
            Group name
            <input autoFocus maxLength={255} value={groupName} onChange={(event) => setGroupName(event.currentTarget.value)} required className={inputClassName} placeholder="e.g. Finance Team" />
          </label>
          <label className={labelClassName}>
            Description
            <textarea maxLength={4000} rows={3} value={groupDescription} onChange={(event) => setGroupDescription(event.currentTarget.value)} className={`${inputClassName} resize-y`} placeholder="What does this group represent?" />
          </label>
          <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={() => setGroupFormOpen(false)} disabled={saving}>Cancel</Button>
            <Button type="submit" loading={saving} disabled={!groupName.trim()}>{editingGroup ? "Save changes" : "Create group"}</Button>
          </div>
        </form>
      </Dialog>

      <Dialog
        open={Boolean(managedWorkspace)}
        title={managedWorkspace ? `${managedWorkspace.name} access` : "Workspace access"}
        description="Assign organization members directly or grant access to an entire group. Membership and group assignments remain organization-scoped."
        onClose={() => setManagedWorkspace(null)}
        className="w-[min(100%-2rem,54rem)]"
      >
        {managedWorkspace && (
          <div className="space-y-6">
            {workspaceAccessError && <InlineMessage message={workspaceAccessError} variant="error" onClose={() => setWorkspaceAccessError(null)} />}
            {workspaceAccessLoading ? <LoadingPanel label="Loading workspace access…" /> : (
              <>
                <section>
                  <SectionHeader title="Direct members" detail="Specific members assigned to this workspace" />
                  <form className="mb-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_140px_auto]" onSubmit={(event) => { event.preventDefault(); void assignWorkspaceMember(); }}>
                    <select aria-label="Organization member" value={newWorkspaceMemberId} onChange={(event) => setNewWorkspaceMemberId(event.currentTarget.value)} disabled={managedWorkspace.status !== "active" || saving || availableWorkspaceMembers.length === 0} className={inputClassName}>
                      <option value="">Select member…</option>
                      {availableWorkspaceMembers.map((member) => <option key={member.membershipId} value={member.membershipId}>{member.username} · {member.email}</option>)}
                    </select>
                    <select aria-label="Workspace role" value={newWorkspaceMemberRole} onChange={(event) => setNewWorkspaceMemberRole(event.currentTarget.value as WorkspaceMemberAssignment["workspaceRole"])} disabled={managedWorkspace.status !== "active" || saving} className={inputClassName}>
                      <option value="viewer">Viewer</option><option value="editor">Editor</option><option value="admin">Workspace admin</option>
                    </select>
                    <Button type="submit" loading={saving} disabled={managedWorkspace.status !== "active" || !newWorkspaceMemberId}><Plus size={14} /> Add</Button>
                  </form>
                  <AssignmentTable
                    empty="No direct members are assigned to this workspace."
                    headers={["MEMBER", "ORGANIZATION ROLE", "WORKSPACE ROLE", "STATUS", ""]}
                    rows={workspaceMembers.map((member) => ({
                      key: member.assignmentId,
                      cells: <>
                        <td className="px-3 py-3"><p className="font-semibold">{member.username}</p><p className="mt-0.5 text-xs text-muted">{member.email}</p></td>
                        <td className="px-3 py-3 text-sm text-muted">{roleLabel(member.organizationRole)}</td>
                        <td className="px-3 py-3">
                          {member.status === "active" ? (
                            <div className="flex min-w-44 items-center gap-2">
                              <select
                                aria-label={`Workspace role for ${member.username}`}
                                value={workspaceRoleDrafts[member.membershipId] ?? member.workspaceRole}
                                onChange={(event) => changeWorkspaceMemberRole(member.membershipId, event.currentTarget.value as WorkspaceMemberAssignment["workspaceRole"])}
                                disabled={saving || managedWorkspace.status !== "active"}
                                className="h-9 min-w-0 rounded-lg border border-border bg-surface px-2 text-xs"
                              >
                                <option value="viewer">Viewer</option><option value="editor">Editor</option><option value="admin">Workspace admin</option>
                              </select>
                              <Button size="sm" variant="secondary" onClick={() => void saveWorkspaceMemberRole(member.membershipId)} disabled={saving || (workspaceRoleDrafts[member.membershipId] ?? member.workspaceRole) === member.workspaceRole}>Save</Button>
                            </div>
                          ) : <span className="text-sm text-muted">{roleLabel(member.workspaceRole)}</span>}
                        </td>
                        <td className="px-3 py-3">{statusBadge(member.status)}</td>
                        <td className="px-3 py-3 text-right">{member.status === "active" && <Button size="sm" variant="ghost" onClick={() => void revokeWorkspaceMember(member.membershipId)} disabled={saving}>Remove</Button>}</td>
                      </>,
                    }))}
                  />
                </section>

                <section>
                  <SectionHeader title="Group access" detail="Grant the same workspace role to every active member of a group" />
                  <form className="mb-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_140px_auto]" onSubmit={(event) => { event.preventDefault(); void assignWorkspaceGroup(); }}>
                    <select aria-label="Organization group" value={newWorkspaceGroupId} onChange={(event) => setNewWorkspaceGroupId(event.currentTarget.value)} disabled={managedWorkspace.status !== "active" || saving || availableWorkspaceGroups.length === 0} className={inputClassName}>
                      <option value="">Select group…</option>
                      {availableWorkspaceGroups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
                    </select>
                    <select aria-label="Group workspace role" value={newWorkspaceGroupRole} onChange={(event) => setNewWorkspaceGroupRole(event.currentTarget.value as WorkspaceGroupGrant["role"])} disabled={managedWorkspace.status !== "active" || saving} className={inputClassName}>
                      <option value="viewer">Viewer</option><option value="editor">Editor</option><option value="admin">Workspace admin</option>
                    </select>
                    <Button type="submit" loading={saving} disabled={managedWorkspace.status !== "active" || !newWorkspaceGroupId}><Plus size={14} /> Grant</Button>
                  </form>
                  <AssignmentTable
                    empty="No groups have been granted access to this workspace."
                    headers={["GROUP", "MEMBERS", "WORKSPACE ROLE", "STATUS", ""]}
                    rows={workspaceGroupGrants.map((grant) => ({
                      key: grant.id,
                      cells: <>
                        <td className="px-3 py-3 font-semibold">{grant.groupName}</td>
                        <td className="px-3 py-3 text-sm text-muted">{groups.find((group) => group.id === grant.groupId)?.memberCount ?? "—"}</td>
                        <td className="px-3 py-3">
                          {grant.groupStatus === "active" && managedWorkspace.status === "active" ? (
                            <div className="flex min-w-44 items-center gap-2">
                              <select
                                aria-label={`Workspace role for group ${grant.groupName}`}
                                value={workspaceGroupRoleDrafts[grant.groupId] ?? grant.role}
                                onChange={(event) => changeWorkspaceGroupRole(grant.groupId, event.currentTarget.value as WorkspaceGroupGrant["role"])}
                                disabled={saving}
                                className="h-9 min-w-0 rounded-lg border border-border bg-surface px-2 text-xs"
                              >
                                <option value="viewer">Viewer</option><option value="editor">Editor</option><option value="admin">Workspace admin</option>
                              </select>
                              <Button size="sm" variant="secondary" onClick={() => void saveWorkspaceGroupRole(grant.groupId)} disabled={saving || (workspaceGroupRoleDrafts[grant.groupId] ?? grant.role) === grant.role}>Save</Button>
                            </div>
                          ) : <span className="text-sm text-muted">{roleLabel(grant.role)}</span>}
                        </td>
                        <td className="px-3 py-3">{statusBadge(grant.groupStatus)}</td>
                        <td className="px-3 py-3 text-right"><Button size="sm" variant="ghost" onClick={() => void revokeWorkspaceGroup(grant.groupId)} disabled={saving}>Revoke</Button></td>
                      </>,
                    }))}
                  />
                  {managedWorkspace.status === "archived" && <p className="mt-2 text-xs text-muted">This workspace is archived. New member and group assignments are disabled until it is restored.</p>}
                </section>
              </>
            )}
          </div>
        )}
      </Dialog>

      <Dialog
        open={Boolean(managedGroup)}
        title={managedGroup ? `${managedGroup.name} members` : "Group members"}
        description="Group membership is limited to active members of this organization. Workspace permissions are managed separately."
        onClose={() => setManagedGroup(null)}
        className="w-[min(100%-2rem,48rem)]"
      >
        {managedGroup && (
          <div className="space-y-4">
            {groupMembersError && <InlineMessage message={groupMembersError} variant="error" onClose={() => setGroupMembersError(null)} />}
            <form className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]" onSubmit={(event) => { event.preventDefault(); void assignGroupMember(); }}>
              <select aria-label="Organization member to add" value={newGroupMemberId} onChange={(event) => setNewGroupMemberId(event.currentTarget.value)} disabled={managedGroup.status !== "active" || saving || groupMembersLoading || availableGroupMembers.length === 0} className={inputClassName}>
                <option value="">Select organization member…</option>
                {availableGroupMembers.map((member) => <option key={member.membershipId} value={member.membershipId}>{member.username} · {member.email}</option>)}
              </select>
              <Button type="submit" loading={saving} disabled={managedGroup.status !== "active" || !newGroupMemberId}><Plus size={14} /> Add member</Button>
            </form>
            {groupMembersLoading ? <LoadingPanel label="Loading group members…" /> : (
              <AssignmentTable
                empty="This group has no members yet."
                headers={["MEMBER", "ORGANIZATION ROLE", ""]}
                rows={groupMembers.map((member) => ({
                  key: member.assignmentId,
                  cells: <>
                    <td className="px-3 py-3"><p className="font-semibold">{member.username}</p><p className="mt-0.5 text-xs text-muted">{member.email}</p></td>
                    <td className="px-3 py-3 text-sm text-muted">{roleLabel(member.organizationRole)}</td>
                    <td className="px-3 py-3 text-right"><Button size="sm" variant="ghost" onClick={() => void revokeGroupMember(member.membershipId)} disabled={saving}>Remove</Button></td>
                  </>,
                }))}
              />
            )}
            {managedGroup.status === "archived" && <p className="text-xs text-muted">This group is archived. Restore it before adding members.</p>}
          </div>
        )}
      </Dialog>

      <ConfirmDialog
        open={Boolean(pendingStatusAction)}
        title={`${pendingStatusAction?.nextStatus === "archived" ? "Archive" : "Restore"} ${pendingStatusAction?.kind ?? "item"}`}
        description={pendingStatusAction?.isDefault && pendingStatusAction.nextStatus === "archived"
          ? "The default workspace cannot be archived."
          : pendingStatusAction?.nextStatus === "archived"
            ? `Archive “${pendingStatusAction?.name}”? Existing data is retained, but new workspace assignments will be blocked.`
            : `Restore “${pendingStatusAction?.name}” so it can be used again.`}
        confirmLabel={pendingStatusAction?.nextStatus === "archived" ? "Archive" : "Restore"}
        destructive={pendingStatusAction?.nextStatus === "archived"}
        pending={saving}
        onClose={() => setPendingStatusAction(null)}
        onConfirm={() => void confirmStatusChange()}
      />
    </PageFrame>
  );
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto w-full max-w-[1600px] p-4 sm:p-6 xl:p-8">{children}</div>;
}

function LoadingPanel({ label }: { label: string }) {
  return <div className="flex items-center justify-center gap-3 px-5 py-12 text-sm text-muted"><RefreshCw size={16} className="animate-spin" />{label}</div>;
}

function MessagePanel({ title, message, variant = "neutral" }: { title: string; message: string; variant?: "neutral" | "error" }) {
  return (
    <section className="mx-auto mt-8 max-w-2xl rounded-2xl border border-border bg-surface p-6 sm:p-8">
      <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-xl ${variant === "error" ? "bg-rose-50 text-danger" : "bg-brand-soft text-brand"}`}>
        {variant === "error" ? <CircleAlert size={20} /> : <Building2 size={20} />}
      </div>
      <h1 className="text-xl font-semibold">{title}</h1>
      <p className="mt-2 text-sm leading-6 text-muted">{message}</p>
    </section>
  );
}

function InlineMessage({ message, variant, onClose }: { message: string; variant: "error" | "success"; onClose: () => void }) {
  return (
    <div role={variant === "error" ? "alert" : "status"} className={`mb-4 flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${variant === "error" ? "border-rose-200 bg-rose-50 text-rose-900" : "border-emerald-200 bg-emerald-50 text-emerald-900"}`}>
      {variant === "error" ? <CircleAlert size={17} className="mt-0.5 shrink-0" /> : <Check size={17} className="mt-0.5 shrink-0" />}
      <p className="min-w-0 flex-1">{message}</p>
      <button type="button" aria-label="Dismiss message" onClick={onClose} className="rounded-md p-0.5 opacity-70 hover:opacity-100"><X size={15} /></button>
    </div>
  );
}

function MetricCard({ label, value, hint, icon: Icon }: { label: string; value: string; hint: string; icon: LucideIcon }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3"><p className="text-sm text-muted">{label}</p><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-soft text-brand"><Icon size={17} /></span></div>
      <p className="mt-4 text-3xl font-semibold tracking-tight">{value}</p>
      <p className="mt-1 text-xs text-muted">{hint}</p>
    </div>
  );
}

function TabButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active} className={`inline-flex min-h-10 items-center gap-2 rounded-xl px-3 text-sm font-semibold transition ${active ? "bg-brand-soft text-brand-contrast" : "text-muted hover:bg-background hover:text-foreground"}`}>
      {icon}{children}
    </button>
  );
}

function WorkspaceTable({ workspaces, onEdit, onManage, onStatusChange }: {
  workspaces: OrganizationWorkspace[];
  onEdit: (workspace: OrganizationWorkspace) => void;
  onManage: (workspace: OrganizationWorkspace) => void;
  onStatusChange: (workspace: OrganizationWorkspace) => void;
}) {
  if (workspaces.length === 0) return <EmptyTable title="No workspaces yet" message="Create a workspace for a team, department, or project." />;
  return (
    <DataTable className="min-w-[880px]">
      <thead className={tableHeaderClassName}><tr><th className="px-5 py-3">WORKSPACE</th><th className="px-4 py-3">MEMBERS</th><th className="px-4 py-3">GROUPS</th><th className="px-4 py-3">STATUS</th><th className="px-4 py-3">ROLE</th><th className="px-4 py-3 text-right">ACTIONS</th></tr></thead>
      <tbody>{workspaces.map((workspace) => (
        <tr key={workspace.id} className="border-t border-border/70 align-middle">
          <td className="px-5 py-4"><div className="flex min-w-0 items-start gap-3"><span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand"><FolderKanban size={17} /></span><div className="min-w-0"><p className="font-semibold">{workspace.name}{workspace.isDefault && <span className="ml-2 text-[10px] font-medium uppercase tracking-wide text-muted">Default</span>}</p>{workspace.description && <p className="mt-1 max-w-lg text-xs leading-5 text-muted">{workspace.description}</p>}</div></div></td>
          <td className="px-4 py-4 text-sm">{workspace.memberCount}</td>
          <td className="px-4 py-4 text-sm">{workspace.groupCount}</td>
          <td className="px-4 py-4">{statusBadge(workspace.status)}</td>
          <td className="px-4 py-4 text-sm text-muted">{workspace.currentUserRole ? roleLabel(workspace.currentUserRole) : "—"}</td>
          <td className="px-4 py-4"><div className="flex justify-end gap-1"><Button size="sm" variant="ghost" onClick={() => onManage(workspace)}><Users size={14} /> Access</Button><Button size="sm" variant="ghost" onClick={() => onEdit(workspace)}><Pencil size={14} /> Edit</Button><Button size="sm" variant="ghost" disabled={workspace.isDefault && workspace.status === "active"} title={workspace.isDefault && workspace.status === "active" ? "The default workspace cannot be archived" : undefined} onClick={() => onStatusChange(workspace)}>{workspace.status === "active" ? "Archive" : "Restore"}</Button></div></td>
        </tr>
      ))}</tbody>
    </DataTable>
  );
}

function GroupTable({ groups, onEdit, onManageMembers, onStatusChange }: {
  groups: OrganizationGroup[];
  onEdit: (group: OrganizationGroup) => void;
  onManageMembers: (group: OrganizationGroup) => void;
  onStatusChange: (group: OrganizationGroup) => void;
}) {
  if (groups.length === 0) return <EmptyTable title="No groups yet" message="Create groups to assign workspace permissions to multiple members together." />;
  return (
    <DataTable className="min-w-[780px]">
      <thead className={tableHeaderClassName}><tr><th className="px-5 py-3">GROUP</th><th className="px-4 py-3">MEMBERS</th><th className="px-4 py-3">WORKSPACES</th><th className="px-4 py-3">STATUS</th><th className="px-4 py-3 text-right">ACTIONS</th></tr></thead>
      <tbody>{groups.map((group) => (
        <tr key={group.id} className="border-t border-border/70">
          <td className="px-5 py-4"><div className="flex min-w-0 items-start gap-3"><span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand"><UsersRound size={17} /></span><div className="min-w-0"><p className="font-semibold">{group.name}</p>{group.description && <p className="mt-1 max-w-lg text-xs leading-5 text-muted">{group.description}</p>}</div></div></td>
          <td className="px-4 py-4 text-sm">{group.memberCount}</td><td className="px-4 py-4 text-sm">{group.workspaceCount}</td><td className="px-4 py-4">{statusBadge(group.status)}</td>
          <td className="px-4 py-4"><div className="flex justify-end gap-1"><Button size="sm" variant="ghost" onClick={() => onManageMembers(group)}><Users size={14} /> Members</Button><Button size="sm" variant="ghost" onClick={() => onEdit(group)}><Pencil size={14} /> Edit</Button><Button size="sm" variant="ghost" onClick={() => onStatusChange(group)}>{group.status === "active" ? "Archive" : "Restore"}</Button></div></td>
        </tr>
      ))}</tbody>
    </DataTable>
  );
}

function MembersTable({ members }: { members: OrganizationMember[] }) {
  if (members.length === 0) return <EmptyTable title="No organization members" message="Memberships will appear here when accounts are added to this organization." />;
  return (
    <DataTable className="min-w-[740px]">
      <thead className={tableHeaderClassName}><tr><th className="px-5 py-3">MEMBER</th><th className="px-4 py-3">ORGANIZATION ROLE</th><th className="px-4 py-3">STATUS</th><th className="px-4 py-3">MEMBERSHIP ID</th></tr></thead>
      <tbody>{members.map((member) => (
        <tr key={member.membershipId} className="border-t border-border/70">
          <td className="px-5 py-4"><p className="font-semibold">{member.username}</p><p className="mt-0.5 text-xs text-muted">{member.email || "No email recorded"}</p></td>
          <td className="px-4 py-4 text-sm">{roleLabel(member.role)}</td><td className="px-4 py-4">{statusBadge(member.status as "active" | "invited" | "suspended" | "revoked")}</td>
          <td className="px-4 py-4 font-mono text-[11px] text-muted">{member.membershipId}</td>
        </tr>
      ))}</tbody>
    </DataTable>
  );
}

function AssignmentTable({ empty, headers, rows }: { empty: string; headers: string[]; rows: Array<{ key: string; cells: React.ReactNode }> }) {
  if (rows.length === 0) return <div className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-xs text-muted">{empty}</div>;
  return (
    <DataTable className="min-w-[650px] text-xs">
      <thead className={tableHeaderClassName}><tr>{headers.map((header, index) => <th key={`${header}-${index}`} className={`px-3 py-2.5 ${index === headers.length - 1 ? "text-right" : ""}`}>{header}</th>)}</tr></thead>
      <tbody>{rows.map((row) => <tr key={row.key} className="border-t border-border/70 align-middle">{row.cells}</tr>)}</tbody>
    </DataTable>
  );
}

function SectionHeader({ title, detail }: { title: string; detail: string }) {
  return <div className="mb-3"><h3 className="text-sm font-semibold">{title}</h3><p className="mt-1 text-xs text-muted">{detail}</p></div>;
}

function EmptyTable({ title, message }: { title: string; message: string }) {
  return <div className="px-5 py-12 text-center"><span className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-background text-muted"><Layers3 size={20} /></span><h3 className="mt-3 text-sm font-semibold">{title}</h3><p className="mx-auto mt-1 max-w-md text-xs leading-5 text-muted">{message}</p></div>;
}
