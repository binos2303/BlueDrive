import assert from "node:assert/strict";
import test from "node:test";
// @ts-expect-error Node 24 provides registerHooks; this project uses Node 20 type declarations.
import { registerHooks } from "node:module";

// Node's test runner needs the same @/ resolution that Next supplies at runtime.
registerHooks({ resolve(specifier: string, context: unknown, nextResolve: (specifier: string, context: unknown) => unknown) {
  return nextResolve(specifier.startsWith("@/") ? new URL(`../${specifier.slice(2)}.ts`, import.meta.url).href : specifier, context);
} });
const { requestAccountApi } = await import("./account-service.ts");
const { setActiveWorkspaceSelection, clearActiveWorkspaceSelection, syncWorkspaceIdentity } = await import("./workspace-context.ts");
const { captureDriveNewDestination } = await import("./drive-new-destination.ts");

test("New follows the selected Drive root and keeps the captured destination through workspace switches", async (context) => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalBase = process.env.NEXT_PUBLIC_API_BASE_URL;
  const storage = new Map<string, string>();
  const location = { pathname: "/drive" };
  Object.defineProperty(globalThis, "window", { configurable: true, value: {
    location,
    localStorage: { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => { storage.set(key, value); }, removeItem: (key: string) => { storage.delete(key); } },
    dispatchEvent: () => true,
  } });
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://api.example.test";
  const calls: Headers[] = [];
  context.mock.method(globalThis, "fetch", async (_input: unknown, init: RequestInit) => {
    calls.push(new Headers(init.headers));
    return Response.json({ ok: true });
  });
  try {
    syncWorkspaceIdentity({ profile: { username: "alex", email: "alex@example.test" }, account: { type: "individual", tenant: null, upgradeEligible: false }, memberships: [] });
    const personal = captureDriveNewDestination("root", 99);
    assert.deepEqual(personal, { folderId: null, workspaceId: null });
    setActiveWorkspaceSelection({ tenantId: "tenant-a", workspaceId: "workspace-a", username: "alex" });
    location.pathname = "/drive/workspaces/workspace-a/files";
    const originalDestination = captureDriveNewDestination("root", 99);
    assert.deepEqual(originalDestination, { folderId: null, workspaceId: "workspace-a" });
    assert.deepEqual(captureDriveNewDestination("current", 42), { folderId: 42, workspaceId: "workspace-a" });
    setActiveWorkspaceSelection({ tenantId: "tenant-b", workspaceId: "workspace-b", username: "alex" });
    location.pathname = "/drive/workspaces/workspace-b/files";
    await requestAccountApi("/files/api/uploads/", { workspaceId: personal.workspaceId, headers: { "X-Workspace-ID": "stale-workspace" } });
    await requestAccountApi("/drive/api/folders/", { workspaceId: originalDestination.workspaceId });
    await requestAccountApi("/files/api/uploads/session-in-a/complete/", { workspaceId: originalDestination.workspaceId });
    await requestAccountApi("/drive/api/items/?view=drive");
    await requestAccountApi("/drive/api/folder-tree/", { workspaceId: "workspace-a" });
    await requestAccountApi("/drive/api/folder-tree/", { workspaceId: null });
    assert.equal(calls[0].has("X-Workspace-ID"), false, "a picker opened in My Drive retains its personal destination");
    assert.equal(calls[1].get("X-Workspace-ID"), "workspace-a", "New folder retains the workspace where its dialog was opened");
    assert.equal(calls[2].get("X-Workspace-ID"), "workspace-a", "a queued upload retains its original workspace");
    assert.equal(calls[3].get("X-Workspace-ID"), "workspace-b", "ordinary browsing still follows the selected workspace");
    assert.equal(calls[4].get("X-Workspace-ID"), "workspace-a", "a folder tree is pinned to its own workspace");
    assert.equal(calls[5].has("X-Workspace-ID"), false, "the My Drive tree requests personal folders");
    assert.equal(captureDriveNewDestination("root", null).workspaceId, "workspace-b");
    location.pathname = "/drive/workspaces/linked-workspace/files";
    await requestAccountApi("/drive/api/items/?view=drive");
    assert.equal(calls[6].get("X-Workspace-ID"), "linked-workspace", "a deep link requests its own workspace before saved selection is resolved");
    clearActiveWorkspaceSelection();
    location.pathname = "/drive";
    assert.deepEqual(captureDriveNewDestination("root", null), { folderId: null, workspaceId: null });
  } finally {
    if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
    else Reflect.deleteProperty(globalThis, "window");
    if (originalBase === undefined) delete process.env.NEXT_PUBLIC_API_BASE_URL;
    else process.env.NEXT_PUBLIC_API_BASE_URL = originalBase;
  }
});
