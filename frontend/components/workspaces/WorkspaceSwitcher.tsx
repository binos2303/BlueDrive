"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  Check,
  ChevronDown,
  Clock3,
  Copy,
  Layers,
  Link2,
  LoaderCircle,
  LogIn,
  Plus,
} from "lucide-react";
import { useAccount } from "@/components/account/AccountProvider";
import Dialog from "@/components/ui/Dialog";
import Button from "@/components/ui/Button";
import {
  clearActiveWorkspaceSelection,
  getSavedWorkspaceSelection,
  setActiveWorkspaceSelection,
  FOLDER_TREE_REFRESH_EVENT,
  WORKSPACES_UPDATED_EVENT,
  WORKSPACE_CHANGED_EVENT,
} from "@/lib/workspace-context";
import {
  acceptWorkspaceInvite,
  createMyWorkspace,
  createWorkspaceInvite,
  getMyWorkspaces,
  type InviteRole,
  type OrganizationWorkspace,
} from "@/lib/workspace-service";

type DialogMode = "create" | "invite" | "join" | null;

function initials(value: string): string {
  const words = value.trim().split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map((word) => word[0]?.toUpperCase() ?? "").join("") || "U";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function tokenFromInput(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    const url = new URL(trimmed, window.location.origin);
    return url.searchParams.get("token") ?? trimmed;
  } catch {
    return trimmed;
  }
}

export default function WorkspaceSwitcher() {
  const router = useRouter();
  const { state: accountState } = useAccount();
  const account = accountState.status === "loaded" ? accountState.account : null;
  const username = account?.profile.username ?? "";
  const ownInitials = initials(username || account?.profile.email || "User");

  const [workspaces, setWorkspaces] = useState<OrganizationWorkspace[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [dialogMode, setDialogMode] = useState<DialogMode>(null);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [createName, setCreateName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [defaultMemberRole, setDefaultMemberRole] = useState<InviteRole>("viewer");
  const [inviteWorkspaceId, setInviteWorkspaceId] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<InviteRole>("viewer");
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [copiedInvite, setCopiedInvite] = useState(false);
  const [joinInput, setJoinInput] = useState("");

  const manageableWorkspaces = useMemo(
    () => workspaces.filter((workspace) => workspace.canManage),
    [workspaces],
  );

  const reloadWorkspaces = useCallback(async () => {
    if (!username) return [] as OrganizationWorkspace[];
    setLoading(true);
    setLoadError(null);
    try {
      const result = await getMyWorkspaces();
      setWorkspaces(result.filter((workspace) => workspace.status === "active"));
      const saved = getSavedWorkspaceSelection();
      const savedAvailable = Boolean(
        saved && saved.username === username && result.some(
          (workspace) => workspace.id === saved.workspaceId && workspace.tenantId === saved.tenantId && workspace.status === "active",
        ),
      );
      if (savedAvailable && saved) {
        setSelectedWorkspaceId(saved.workspaceId);
        setActiveWorkspaceSelection(saved);
      } else {
        if (saved?.username === username) clearActiveWorkspaceSelection();
        setSelectedWorkspaceId("");
      }
      return result;
    } catch (error) {
      setLoadError(errorMessage(error));
      setWorkspaces([]);
      return [] as OrganizationWorkspace[];
    } finally {
      setLoading(false);
    }
  }, [username]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void reloadWorkspaces(); }, 0);
    const onUpdated = () => { void reloadWorkspaces(); };
    const onWorkspaceChanged = () => {
      const saved = getSavedWorkspaceSelection();
      setSelectedWorkspaceId(saved?.username === username ? saved.workspaceId : "");
    };
    window.addEventListener(WORKSPACES_UPDATED_EVENT, onUpdated);
    window.addEventListener(WORKSPACE_CHANGED_EVENT, onWorkspaceChanged);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener(WORKSPACES_UPDATED_EVENT, onUpdated);
      window.removeEventListener(WORKSPACE_CHANGED_EVENT, onWorkspaceChanged);
    };
  }, [reloadWorkspaces, username]);


  const effectiveInviteWorkspaceId = manageableWorkspaces.some(
    (workspace) => workspace.id === inviteWorkspaceId,
  ) ? inviteWorkspaceId : (manageableWorkspaces[0]?.id ?? "");

  function openDialog(mode: Exclude<DialogMode, null>) {
    setFormError(null);
    setInviteUrl(null);
    setCopiedInvite(false);
    if (mode === "invite") {
      setInviteEmail("");
      const selected = manageableWorkspaces.find((workspace) => workspace.id === inviteWorkspaceId)
        ?? manageableWorkspaces[0];
      if (selected) {
        setInviteWorkspaceId(selected.id);
        setInviteRole(selected.defaultMemberRole);
      }
    }
    if (mode === "join") setJoinInput("");
    setDialogMode(mode);
  }

  function closeDialog() {
    if (submitting) return;
    setDialogMode(null);
    setFormError(null);
    setInviteUrl(null);
  }

  function activateWorkspace(workspace: OrganizationWorkspace, notify = true) {
    if (!username) return;
    setSelectedWorkspaceId(workspace.id);
    setActiveWorkspaceSelection({
      tenantId: workspace.tenantId,
      workspaceId: workspace.id,
      username,
    }, { notify });
  }

  function selectWorkspace(workspace: OrganizationWorkspace) {
    activateWorkspace(workspace);
    router.push("/drive");
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const workspace = await createMyWorkspace({
        name: createName.trim(),
        description: createDescription.trim(),
        default_member_role: defaultMemberRole,
      });
      await reloadWorkspaces();
      setSelectedWorkspaceId(workspace.id);
      setActiveWorkspaceSelection({ tenantId: workspace.tenantId, workspaceId: workspace.id, username });
      window.dispatchEvent(new Event(WORKSPACES_UPDATED_EVENT));
      setCreateName("");
      setCreateDescription("");
      setDialogMode(null);
      router.push("/drive");
    } catch (error) {
      setFormError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setFormError(null);
    setInviteUrl(null);
    try {
      const result = await createWorkspaceInvite(effectiveInviteWorkspaceId, {
        email: inviteEmail.trim(),
        role: inviteRole,
      });
      const url = new URL("/workspace-invite", window.location.origin);
      url.searchParams.set("token", result.inviteToken);
      setInviteUrl(url.toString());
      window.dispatchEvent(new Event(WORKSPACES_UPDATED_EVENT));
    } catch (error) {
      setFormError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleJoin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const token = tokenFromInput(joinInput);
      if (!token) throw new Error("Paste a workspace invitation link or token.");
      const result = await acceptWorkspaceInvite(token);
      await reloadWorkspaces();
      setSelectedWorkspaceId(result.workspace.id);
      setActiveWorkspaceSelection({
        tenantId: result.workspace.tenantId,
        workspaceId: result.workspace.id,
        username,
      });
      window.dispatchEvent(new Event(WORKSPACES_UPDATED_EVENT));
      setJoinInput("");
      setDialogMode(null);
      router.push("/drive");
    } catch (error) {
      setFormError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  async function copyInvite() {
    if (!inviteUrl) return;
    try {
      await navigator.clipboard.writeText(inviteUrl);
      setCopiedInvite(true);
    } catch {
      setFormError("Could not copy automatically. Select and copy the invitation link below.");
    }
  }

  if (accountState.status !== "loaded") return null;

  return (
    <section className="mx-3 mb-3 rounded-2xl border border-border bg-background p-3" aria-label="Workspaces">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 rounded-lg px-1 py-1 text-left"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand-contrast">
          <Layers size={15} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[12px] font-semibold text-foreground">Workspaces</span>
        </span>
        {loading ? <LoaderCircle size={14} className="animate-spin text-muted" /> : expanded ? <ChevronDown size={15} className="text-muted" /> : <ChevronDown size={15} className="-rotate-90 text-muted" />}
      </button>

      {expanded && (
        <>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <button type="button" onClick={() => openDialog("create")} className="flex h-[30px] items-center justify-center gap-1 rounded-lg border border-border bg-surface px-1 text-[11px] font-medium text-foreground hover:bg-brand-soft hover:text-brand-contrast">
              <Plus size={12} /> Create
            </button>
            <button type="button" onClick={() => openDialog("join")} className="flex h-[30px] items-center justify-center gap-1 rounded-lg border border-border bg-surface px-1 text-[11px] font-medium text-foreground hover:bg-brand-soft hover:text-brand-contrast">
              <LogIn size={12} /> Join
            </button>
          </div>

          <div className="mt-2 max-h-52 space-y-1 overflow-y-auto pr-0.5">
            {workspaces.length === 0 && !loading && !loadError && (
              <p className="px-1 py-2 text-[11px] leading-4 text-muted">No workspaces yet...</p>
            )}
            {workspaces.map((workspace) => {
              const active = selectedWorkspaceId === workspace.id;
              const avatar = workspace.isOwnedByMe ? ownInitials : workspace.createdByInitials || initials(workspace.createdByUsername);
              return (
                <div key={workspace.id} className={`flex items-center gap-1 rounded-xl pr-1 transition-colors ${active ? "bg-brand-soft" : "hover:bg-surface"}`}>
                  <button
                    type="button"
                    onClick={() => selectWorkspace(workspace)}
                    aria-pressed={active}
                    title={`${workspace.name} · created by ${workspace.createdByUsername}`}
                    className="flex min-w-0 flex-1 items-center gap-2 rounded-xl px-1.5 py-2 text-left"
                  >
                    <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${workspace.isOwnedByMe ? "bg-brand-contrast text-white" : "border border-border bg-surface text-foreground"}`}>
                      {avatar}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className={`block truncate text-xs font-semibold ${active ? "text-brand-contrast" : "text-foreground"}`}>{workspace.name}</span>
                      <span className="block truncate text-[10px] text-muted">{workspace.isOwnedByMe ? "Created by you" : `By ${workspace.createdByUsername}`} · {workspace.currentUserRole ?? "Member"}</span>
                    </span>
                    {active && <Check size={13} className="shrink-0 text-brand-contrast" />}
                  </button>
                  {workspace.canManage && (
                    <button
                      type="button"
                      onClick={() => {
                        // A silent context switch avoids the Drive browser's
                        // folder-reset navigation racing the timeline route.
                        activateWorkspace(workspace, false);
                        window.dispatchEvent(new Event(FOLDER_TREE_REFRESH_EVENT));
                        router.push(`/drive/workspaces/${encodeURIComponent(workspace.id)}/activity`);
                      }}
                      aria-label={`Open ${workspace.name} timeline`}
                      title="Workspace timeline"
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-surface hover:text-brand-contrast"
                    >
                      <Clock3 size={13} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
          {loadError && <p role="status" className="mt-2 text-[11px] leading-4 text-danger">{loadError}</p>}
        </>
      )}

      <Dialog
        open={dialogMode === "create"}
        title="Create a workspace"
        description="Create a shared area for files and collaboration. My Drive remains separate."
        onClose={closeDialog}
      >
        <form className="space-y-4" onSubmit={handleCreate}>
          <label className="block space-y-1.5">
            <span className="text-xs font-semibold text-foreground">Workspace name <span className="text-danger">*</span></span>
            <input autoFocus required maxLength={255} value={createName} onChange={(event) => setCreateName(event.currentTarget.value)} placeholder="e.g. Product launch" className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm outline-none focus:border-brand" />
          </label>
          <label className="block space-y-1.5">
            <span className="text-xs font-semibold text-foreground">Description <span className="font-normal text-muted">(optional)</span></span>
            <textarea rows={3} maxLength={4000} value={createDescription} onChange={(event) => setCreateDescription(event.currentTarget.value)} placeholder="What will this workspace be used for?" className="w-full resize-y rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none focus:border-brand" />
          </label>
          <label className="block space-y-1.5">
            <span className="text-xs font-semibold text-foreground">Default role for invited members</span>
            <select value={defaultMemberRole} onChange={(event) => setDefaultMemberRole(event.currentTarget.value as InviteRole)} className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm outline-none focus:border-brand">
              <option value="viewer">Viewer — can view and download</option>
              <option value="editor">Editor — can add and manage files</option>
            </select>
          </label>
          <div className="rounded-xl border border-border bg-background p-3 text-xs leading-5 text-muted">
            <p className="font-semibold text-foreground">Access policy</p>
            Only people with an invitation link can join. Links expire after 7 days and are tied to the invited email address.
          </div>
          {formError && <p role="alert" className="text-xs leading-5 text-danger">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={closeDialog} disabled={submitting}>Cancel</Button>
            <Button type="submit" loading={submitting} disabled={!createName.trim()}>Create workspace</Button>
          </div>
        </form>
      </Dialog>

      <Dialog
        open={dialogMode === "invite"}
        title={inviteUrl ? "Invitation link created" : "Invite a member"}
        description={inviteUrl ? "Copy the link and send it to the invited person." : "Invitations are tied to the recipient's account email and expire in 7 days."}
        onClose={closeDialog}
      >
        {inviteUrl ? (
          <div className="space-y-4">
            <div className="rounded-xl border border-border bg-background p-3">
              <p className="mb-2 text-xs font-semibold text-foreground">Invitation link</p>
              <input readOnly value={inviteUrl} onFocus={(event) => event.currentTarget.select()} className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-xs text-foreground outline-none" />
            </div>
            <p className="text-xs leading-5 text-muted">The link grants the role selected for this invitation. The recipient must sign in with {inviteEmail || "the invited email address"}.</p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => { setDialogMode(null); setInviteUrl(null); setInviteEmail(""); }}>Done</Button>
              <Button onClick={() => { void copyInvite(); }}><Copy size={14} /> {copiedInvite ? "Copied" : "Copy link"}</Button>
            </div>
          </div>
        ) : (
          <form className="space-y-4" onSubmit={handleInvite}>
            {manageableWorkspaces.length === 0 ? (
              <p className="rounded-xl border border-border bg-background p-3 text-sm leading-6 text-muted">You do not manage any workspace yet. Create one or ask a workspace admin to invite members.</p>
            ) : (
              <>
                <label className="block space-y-1.5">
                  <span className="text-xs font-semibold text-foreground">Workspace</span>
                  <select required value={effectiveInviteWorkspaceId} onChange={(event) => {
                    const nextId = event.currentTarget.value;
                    setInviteWorkspaceId(nextId);
                    const nextWorkspace = manageableWorkspaces.find((workspace) => workspace.id === nextId);
                    if (nextWorkspace) setInviteRole(nextWorkspace.defaultMemberRole);
                  }} className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm outline-none focus:border-brand">
                    {manageableWorkspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
                  </select>
                </label>
                <label className="block space-y-1.5">
                  <span className="text-xs font-semibold text-foreground">Email address</span>
                  <input autoFocus required type="email" maxLength={254} value={inviteEmail} onChange={(event) => setInviteEmail(event.currentTarget.value)} placeholder="colleague@example.com" className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm outline-none focus:border-brand" />
                </label>
                <label className="block space-y-1.5">
                  <span className="text-xs font-semibold text-foreground">Permission</span>
                  <select value={inviteRole} onChange={(event) => setInviteRole(event.currentTarget.value as InviteRole)} className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm outline-none focus:border-brand">
                    <option value="viewer">Viewer — can view and download</option>
                    <option value="editor">Editor — can add and manage files</option>
                  </select>
                </label>
              </>
            )}
            {formError && <p role="alert" className="text-xs leading-5 text-danger">{formError}</p>}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={closeDialog} disabled={submitting}>Cancel</Button>
              <Button type="submit" loading={submitting} disabled={manageableWorkspaces.length === 0 || !inviteEmail.trim() || !effectiveInviteWorkspaceId}><Link2 size={14} /> Create invitation</Button>
            </div>
          </form>
        )}
      </Dialog>

      <Dialog
        open={dialogMode === "join"}
        title="Join a workspace"
        description="Paste an invitation link or token sent to your account email."
        onClose={closeDialog}
      >
        <form className="space-y-4" onSubmit={handleJoin}>
          <label className="block space-y-1.5">
            <span className="text-xs font-semibold text-foreground">Invitation link or token</span>
            <textarea required rows={3} value={joinInput} onChange={(event) => setJoinInput(event.currentTarget.value)} placeholder="https://your-domain/workspace-invite?token=…" className="w-full resize-y rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none focus:border-brand" />
          </label>
          {formError && <p role="alert" className="text-xs leading-5 text-danger">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={closeDialog} disabled={submitting}>Cancel</Button>
            <Button type="submit" loading={submitting} disabled={!joinInput.trim()}><LogIn size={14} /> Join workspace</Button>
          </div>
        </form>
      </Dialog>
    </section>
  );
}
