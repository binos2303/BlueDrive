import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// Execute the production callback with controllable requests; no network or DOM is needed.
const source = ts.createSourceFile("OrganizationAdminPage.tsx", readFileSync(new URL("./OrganizationAdminPage.tsx", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let initializer = "";
function find(node: ts.Node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(source) === "refreshAccess") initializer = node.initializer!.getText(source);
  ts.forEachChild(node, find);
}
find(source);
assert.ok(initializer, "The production access-loading callback must be present");
const compiled = ts.transpileModule(`const refreshAccess = ${initializer};`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;

function deferred() {
  let resolve!: (value: { members: string[] }) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<{ members: string[] }>((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}

function setup() {
  const requests = new Map<string, ReturnType<typeof deferred>>();
  const identity = { current: 0 };
  const state = { loading: false, members: [] as string[], error: null as string | null };
  const load = new Function("useCallback", "tenantId", "accessRequestId", "getWorkspaceMembers", "setAccessLoading", "setAssignments", "setAccessError", "errorMessage", `${compiled}; return refreshAccess;`)(
    (callback: unknown) => callback, "organization-1", identity,
    (_tenant: string, id: string) => { const request = deferred(); requests.set(id, request); return request.promise; },
    (value: boolean) => { state.loading = value; }, (members: string[]) => { state.members = members; },
    (error: string | null) => { state.error = error; }, (error: Error) => error.message,
  ) as (workspace: { id: string }) => Promise<void>;
  return { requests, identity, state, load };
}

test("an older workspace response cannot overwrite the selected workspace or stop its loading state", async () => {
  const { load, requests, state } = setup();
  const a = load({ id: "A" });
  const b = load({ id: "B" });
  requests.get("A")!.resolve({ members: ["member A"] });
  await a;
  assert.deepEqual(state.members, []);
  assert.equal(state.loading, true);
  requests.get("B")!.resolve({ members: ["member B"] });
  await b;
  assert.deepEqual(state.members, ["member B"]);
  assert.equal(state.loading, false);
});

test("a late failure cannot replace current results with another workspace's error", async () => {
  const { load, requests, state } = setup();
  const a = load({ id: "A" });
  const b = load({ id: "B" });
  requests.get("B")!.resolve({ members: ["member B"] });
  await b;
  requests.get("A")!.reject(new Error("A failed"));
  await a;
  assert.deepEqual(state.members, ["member B"]);
  assert.equal(state.error, null);
});

test("closing or leaving the access view invalidates an outstanding response", async () => {
  const { load, requests, state, identity } = setup();
  const a = load({ id: "A" });
  identity.current += 1;
  requests.get("A")!.resolve({ members: ["member A"] });
  await a;
  assert.deepEqual(state.members, []);
});
