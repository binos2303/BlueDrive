"use client";

import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { usePathname, useRouter } from "next/navigation";
import { drivePath, workspaceIdFromPathname } from "@/lib/drive-paths";
import {
  Check,
  ChevronDown,
  HardDrive,
  Layers,
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
  WORKSPACES_UPDATED_EVENT,
  WORKSPACE_CHANGED_EVENT,
} from "@/lib/workspace-context";
import {
  acceptWorkspaceInvite,
  createMyWorkspace,
  getMyWorkspaces,
  type InviteRole,
  type OrganizationWorkspace,
} from "@/lib/workspace-service";

type DialogMode = "create" | "join" | null;

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

export default function WorkspaceSwitcher({ onWorkspaceChange, onNavigate }: {
  onWorkspaceChange?: (workspace: OrganizationWorkspace | null) => void;
  onNavigate?: () => void;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const routeWorkspaceId = workspaceIdFromPathname(pathname);
  const personalDriveRoute = !routeWorkspaceId && (pathname === "/drive" || pathname.startsWith("/drive/"));
  const { state: accountState } = useAccount();
  const account = accountState.status === "loaded" ? accountState.account : null;
  const organizationDrive = account?.myDrive?.ownership === "organization";
  const driveOrganizationName = organizationDrive
    ? account.memberships.find((membership) => membership.id === account.myDrive?.tenantId)?.name ?? "Organization-owned"
    : null;
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
  const [joinInput, setJoinInput] = useState("");
  const loadRequestId = useRef(0);
  const popoverId = useId();
  const popoverRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ top: 64, left: 16 });

  useEffect(() => {
    if (!expanded) return;
    const close = () => popoverRef.current?.hidePopover();
    window.addEventListener("resize", close);
    return () => window.removeEventListener("resize", close);
  }, [expanded]);

  const reloadWorkspaces = useCallback(async () => {
    if (!username) return [] as OrganizationWorkspace[];
    const requestId = ++loadRequestId.current;
    setLoading(true);
    setLoadError(null);
    try {
      const result = (await getMyWorkspaces()).filter((workspace) => !workspace.isDefault);
      if (requestId !== loadRequestId.current) return result;
      setWorkspaces(result.filter((workspace) => workspace.status === "active"));
      const routeWorkspace = result.find((workspace) => workspace.id === routeWorkspaceId && workspace.status === "active");
      if (routeWorkspace) {
        setSelectedWorkspaceId(routeWorkspace.id);
        setActiveWorkspaceSelection({ tenantId: routeWorkspace.tenantId, workspaceId: routeWorkspace.id, username });
        return result;
      }
      if (routeWorkspaceId || personalDriveRoute) {
        clearActiveWorkspaceSelection();
        setSelectedWorkspaceId("");
        if (routeWorkspaceId) setLoadError("This workspace is unavailable or you no longer have access.");
        return result;
      }
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
      if (requestId === loadRequestId.current) {
        setLoadError(errorMessage(error));
        setWorkspaces([]);
      }
      return [] as OrganizationWorkspace[];
    } finally {
      if (requestId === loadRequestId.current) setLoading(false);
    }
  }, [username, routeWorkspaceId, personalDriveRoute]);

  const selectedWorkspace = workspaces.find((workspace) => workspace.id === selectedWorkspaceId) ?? null;
  useEffect(() => { onWorkspaceChange?.(selectedWorkspace); }, [onWorkspaceChange, selectedWorkspace]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void reloadWorkspaces(); }, 0);
    const onUpdated = () => { void reloadWorkspaces(); };
    const onWorkspaceChanged = () => {
      const saved = getSavedWorkspaceSelection();
      if (routeWorkspaceId && saved?.workspaceId !== routeWorkspaceId) {
        // Leaving a management route wins over its pending workspace lookup.
        loadRequestId.current += 1;
        setLoading(false);
      }
      setSelectedWorkspaceId(saved?.username === username ? saved.workspaceId : "");
    };
    window.addEventListener(WORKSPACES_UPDATED_EVENT, onUpdated);
    window.addEventListener(WORKSPACE_CHANGED_EVENT, onWorkspaceChanged);
    return () => {
      loadRequestId.current += 1;
      window.clearTimeout(timer);
      window.removeEventListener(WORKSPACES_UPDATED_EVENT, onUpdated);
      window.removeEventListener(WORKSPACE_CHANGED_EVENT, onWorkspaceChanged);
    };
  }, [reloadWorkspaces, username, routeWorkspaceId]);


  function openDialog(mode: Exclude<DialogMode, null>) {
    popoverRef.current?.hidePopover();
    setFormError(null);
    if (mode === "join") setJoinInput("");
    setDialogMode(mode);
  }

  function closeDialog() {
    if (submitting) return;
    setDialogMode(null);
    setFormError(null);
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
    loadRequestId.current += 1;
    setLoading(false);
    activateWorkspace(workspace);
    popoverRef.current?.hidePopover();
    onNavigate?.();
    router.push(drivePath(workspace.id));
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
      setExpanded(false);
      onNavigate?.();
      router.push(drivePath(workspace.id));
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
      setExpanded(false);
      onNavigate?.();
      router.push(drivePath(result.workspace.id));
    } catch (error) {
      setFormError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  if (accountState.status !== "loaded") return null;

  return (
    <section className="min-w-0" aria-label="Workspace switcher">
      <button type="button" popoverTarget={popoverId} aria-expanded={expanded} aria-controls={popoverId}
        onClick={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setPosition({ top: rect.bottom + 8, left: Math.max(16, Math.min(rect.left, window.innerWidth - 336)) });
        }}
        className="ui-control flex min-h-11 w-full min-w-0 items-center gap-2 rounded-xl border border-border px-3 text-left transition-colors hover:bg-background">
        <Layers size={18} className="shrink-0 text-brand-contrast" />
        <span className="min-w-0 flex-1 truncate text-sm font-medium" title={selectedWorkspace?.name ?? driveOrganizationName ?? undefined}>{selectedWorkspace?.name || (organizationDrive ? `My Drive · ${driveOrganizationName}` : "Workspaces")}</span>
        {loading ? <LoaderCircle size={15} className="shrink-0 animate-spin text-muted" /> : <ChevronDown size={15} className={`shrink-0 text-muted transition-transform ${expanded ? "rotate-180" : ""}`} />}
      </button>
      <div ref={popoverRef} id={popoverId} popover="auto" onToggle={(event) => setExpanded(event.newState === "open")} style={position}
        className="fixed m-0 max-h-[min(70dvh,32rem)] w-80 max-w-[calc(100vw-2rem)] overflow-y-auto rounded-2xl border border-border bg-surface p-2 text-foreground shadow-[var(--shadow-popover)]">
        <button type="button" onClick={() => {
          loadRequestId.current += 1; setLoading(false); setSelectedWorkspaceId("");
          clearActiveWorkspaceSelection(); popoverRef.current?.hidePopover(); onNavigate?.(); router.push("/drive");
        }} aria-pressed={!selectedWorkspaceId} className={`flex min-h-12 w-full items-center gap-3 rounded-xl px-3 py-2 text-left ${!selectedWorkspaceId ? "bg-brand-soft" : "hover:bg-background"}`}>
          <HardDrive size={20} className="shrink-0 text-brand-contrast" /><span className="min-w-0 flex-1 text-sm font-semibold">My Drive{organizationDrive && <span className="block truncate text-xs font-normal text-muted">{driveOrganizationName}</span>}</span>
          {!selectedWorkspaceId && <Check size={16} className="text-brand-contrast" />}
        </button>
        <div className="my-2 grid grid-cols-2 gap-2 border-y border-border py-3">
          <Button variant="secondary" size="sm" onClick={() => openDialog("create")}><Plus size={16} />Create</Button>
          <Button variant="secondary" size="sm" onClick={() => openDialog("join")}><LogIn size={16} />Join</Button>
        </div>
        {loading && workspaces.length === 0 && <p role="status" className="px-3 py-4 text-sm text-muted">Loading workspaces…</p>}
        {workspaces.length === 0 && !loading && !loadError && <p className="px-3 py-4 text-sm leading-6 text-muted">Create a workspace or join with an invitation link.</p>}
        <div className="space-y-1">{workspaces.map((workspace) => {
          const active = selectedWorkspaceId === workspace.id;
          const avatar = workspace.isOwnedByMe ? ownInitials : workspace.createdByInitials || initials(workspace.createdByUsername);
          return <button key={workspace.id} type="button" onClick={() => selectWorkspace(workspace)} aria-pressed={active} title={`${workspace.name} · created by ${workspace.createdByUsername}`}
            className={`flex min-h-14 w-full min-w-0 items-center gap-3 rounded-xl px-3 py-2 text-left ${active ? "bg-brand-soft" : "hover:bg-background"}`}>
            <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${workspace.isOwnedByMe ? "bg-brand-contrast text-on-accent" : "border border-border bg-background text-foreground"}`}>{avatar}</span>
            <span className="min-w-0 flex-1"><span className={`block truncate text-sm font-semibold ${active ? "text-brand-contrast" : "text-foreground"}`}>{workspace.name}</span><span className="block truncate text-xs text-muted">{workspace.isOwnedByMe ? "Created by you" : `By ${workspace.createdByUsername}`} · {workspace.currentUserRole ?? "Member"}</span></span>
            {active && <Check size={16} className="shrink-0 text-brand-contrast" />}
          </button>;
        })}</div>
        {loadError && <div role="status" className="px-3 py-3 text-sm leading-6 text-danger"><p>{loadError}</p><Button variant="ghost" size="sm" onClick={() => { void reloadWorkspaces(); }}>Try again</Button></div>}
      </div>
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
