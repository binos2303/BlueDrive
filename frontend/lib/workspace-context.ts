import type { AccountSnapshot } from "@/lib/account-service";

export const WORKSPACE_CHANGED_EVENT = "securedrive:workspace-changed";
export const WORKSPACES_UPDATED_EVENT = "securedrive:workspaces-updated";
export const FOLDER_TREE_REFRESH_EVENT = "securedrive:folder-tree-refresh";
export const DRIVE_SEARCH_CHANGED_EVENT = "securedrive:drive-search-changed";
export const DRIVE_UPLOAD_COMPLETED_EVENT = "securedrive:upload-completed";

const SELECTION_KEY = "securedrive:workspace-selection:v1";
const IDENTITY_KEY = "securedrive:workspace-identity:v1";

type WorkspaceSelection = {
  tenantId: string;
  workspaceId: string;
  username: string;
};

type WorkspaceIdentity = {
  username: string;
};

let memorySelection: WorkspaceSelection | null = null;
let memorySelectionInitialized = false;
let memoryIdentity: WorkspaceIdentity | null = null;
let memoryIdentityInitialized = false;

function readJson<T>(key: string): T | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) as T : null;
  } catch {
    return null;
  }
}

function safeDispatchWorkspaceChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(WORKSPACE_CHANGED_EVENT));
  }
}

export function getSavedWorkspaceSelection(): WorkspaceSelection | null {
  const selection = memorySelectionInitialized
    ? memorySelection
    : readJson<WorkspaceSelection>(SELECTION_KEY);
  if (
    !selection ||
    typeof selection.tenantId !== "string" ||
    typeof selection.workspaceId !== "string" ||
    typeof selection.username !== "string"
  ) {
    return null;
  }
  return selection;
}

export function getActiveWorkspaceIdForRequest(): string | null {
  const selection = getSavedWorkspaceSelection();
  const identity = memoryIdentityInitialized
    ? memoryIdentity
    : readJson<WorkspaceIdentity>(IDENTITY_KEY);
  if (!selection || !identity || identity.username !== selection.username) {
    return null;
  }
  // Workspace membership may belong to another user's personal tenant. The
  // backend validates the selected workspace UUID on every request.
  return selection.workspaceId;
}

export function setActiveWorkspaceSelection(input: WorkspaceSelection, options: { notify?: boolean } = {}): void {
  if (typeof window === "undefined") return;
  const current = getSavedWorkspaceSelection();
  if (
    current?.tenantId === input.tenantId &&
    current.workspaceId === input.workspaceId &&
    current.username === input.username
  ) {
    return;
  }
  memorySelection = input;
  memorySelectionInitialized = true;
  try {
    window.localStorage.setItem(SELECTION_KEY, JSON.stringify(input));
  } catch {
    // The in-memory value still applies for this page when persistence is blocked.
  }
  if (options.notify !== false) safeDispatchWorkspaceChanged();
}

export function clearActiveWorkspaceSelection(): void {
  if (typeof window === "undefined") return;
  const existed = getSavedWorkspaceSelection() !== null;
  memorySelection = null;
  memorySelectionInitialized = true;
  try {
    window.localStorage.removeItem(SELECTION_KEY);
  } catch {
    // The selection is optional when browser storage is unavailable.
  }
  if (existed) safeDispatchWorkspaceChanged();
}

/** Keep a saved workspace bound to the authenticated user and selected tenant. */
export function syncWorkspaceIdentity(account: AccountSnapshot): void {
  if (typeof window === "undefined") return;

  const next: WorkspaceIdentity = {
    username: account.profile.username,
  };
  const previous = memoryIdentityInitialized
    ? memoryIdentity
    : readJson<WorkspaceIdentity>(IDENTITY_KEY);
  const changed = previous?.username !== next.username;

  memoryIdentity = next;
  memoryIdentityInitialized = true;
  try {
    window.localStorage.setItem(IDENTITY_KEY, JSON.stringify(next));
  } catch {
    // Selection persistence is a convenience, not an access-control boundary.
  }

  if (!changed) return;

  memorySelection = null;
  memorySelectionInitialized = true;
  try {
    window.localStorage.removeItem(SELECTION_KEY);
  } catch {
    // A stale selection will not be used unless its identity matches.
  }
  safeDispatchWorkspaceChanged();
}
