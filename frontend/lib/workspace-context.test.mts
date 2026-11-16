import assert from "node:assert/strict";
import test from "node:test";
import {
  clearActiveWorkspaceSelection,
  getActiveWorkspaceIdForRequest,
  getSavedWorkspaceSelection,
  setActiveWorkspaceSelection,
  syncWorkspaceIdentity,
  WORKSPACE_CHANGED_EVENT,
} from "./workspace-context.ts";

test("workspace navigation and requests stay in sync through switches, reloads and account changes", () => {
  const storage = new Map<string, string>();
  const events = new EventTarget();
  const original = Object.getOwnPropertyDescriptor(globalThis, "window");
  const location = { pathname: "/account/settings" };
  Object.defineProperty(globalThis, "window", { configurable: true, value: {
    location,
    localStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value); },
      removeItem: (key: string) => { storage.delete(key); },
    },
    dispatchEvent: (event: Event) => events.dispatchEvent(event),
  } });
  let notifications = 0;
  events.addEventListener(WORKSPACE_CHANGED_EVENT, () => { notifications += 1; });
  const account = (username: string) => ({
    profile: { username, email: `${username}@example.test` },
    account: { type: "individual" as const, tenant: null, upgradeEligible: false },
    memberships: [],
  });
  try {
    syncWorkspaceIdentity(account("alex"));
    notifications = 0;
    assert.equal(getActiveWorkspaceIdForRequest(), null);
    const selection = { tenantId: "tenant-a", workspaceId: "project-a", username: "alex" };
    setActiveWorkspaceSelection(selection);
    assert.equal(getActiveWorkspaceIdForRequest(), "project-a");
    assert.equal(notifications, 1);
    setActiveWorkspaceSelection(selection);
    syncWorkspaceIdentity(account("alex"));
    assert.equal(getActiveWorkspaceIdForRequest(), "project-a");
    assert.equal(notifications, 1, "remounting the same account must not reset its workspace");

    setActiveWorkspaceSelection({ ...selection, workspaceId: "project-b" });
    assert.equal(getActiveWorkspaceIdForRequest(), "project-b");
    assert.equal(notifications, 2);
    clearActiveWorkspaceSelection();
    assert.equal(getActiveWorkspaceIdForRequest(), null, "Back to My Drive clears request context too");
    assert.equal(getSavedWorkspaceSelection(), null);
    assert.equal(notifications, 3);

    setActiveWorkspaceSelection(selection, { notify: false });
    assert.equal(getActiveWorkspaceIdForRequest(), "project-a");
    assert.equal(notifications, 3, "opening a workspace management route must not race a Drive redirect");
    location.pathname = "/drive/workspaces/linked-workspace/files";
    assert.equal(getActiveWorkspaceIdForRequest(), "linked-workspace", "direct URLs override a saved workspace");
    location.pathname = "/drive/workspaces/project-b/folders/42";
    assert.equal(getActiveWorkspaceIdForRequest(), "project-b", "Back/Forward selects the workspace in the URL");
    location.pathname = "/drive";
    assert.equal(getActiveWorkspaceIdForRequest(), null, "the personal Drive URL cannot inherit a saved workspace");
    location.pathname = "/account/settings";
    assert.equal(getActiveWorkspaceIdForRequest(), "project-a", "account pages preserve the last selected workspace");
    syncWorkspaceIdentity(account("sam"));
    assert.equal(getActiveWorkspaceIdForRequest(), null, "another account must not inherit the selected workspace");
    setActiveWorkspaceSelection(selection);
    assert.equal(getActiveWorkspaceIdForRequest(), null, "a selection bound to another user is ignored");
  } finally {
    if (original) Object.defineProperty(globalThis, "window", original);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
