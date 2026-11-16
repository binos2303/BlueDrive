import assert from "node:assert/strict";
import test from "node:test";
import { drivePath, driveFolderIdFromPathname, workspaceIdFromPathname } from "./drive-paths.ts";

test("Drive paths preserve workspace scope for files, views and folders", () => {
  assert.equal(drivePath(null), "/drive");
  assert.equal(drivePath(null, "folders/42"), "/drive/folders/42");
  assert.equal(drivePath("workspace-a"), "/drive/workspaces/workspace-a/files");
  assert.equal(drivePath("workspace-a", "recent"), "/drive/workspaces/workspace-a/recent");
  assert.equal(drivePath("workspace-a", "folders/42"), "/drive/workspaces/workspace-a/folders/42");
  assert.equal(workspaceIdFromPathname(drivePath("a b")), "a b");
  assert.equal(workspaceIdFromPathname("/drive/workspaces/workspace-b/members"), "workspace-b");
  assert.equal(workspaceIdFromPathname("/drive/workspaces/workspace-a"), "workspace-a");
  assert.equal(workspaceIdFromPathname("/drive/folders/42"), null);
});

test("folder route parsing accepts only positive safe folder IDs in a Drive scope", () => {
  assert.equal(driveFolderIdFromPathname("/drive/folders/42"), 42);
  assert.equal(driveFolderIdFromPathname("/drive/workspaces/a/folders/42"), 42);
  for (const path of ["/drive/folders/0", "/drive/folders/-1", "/drive/folders/9007199254740992", "/drive/workspaces/a/folders/42/extra", "/other/folders/42"]) {
    assert.equal(driveFolderIdFromPathname(path), null);
  }
});
