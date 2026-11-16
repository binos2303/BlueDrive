import test from "node:test";
import assert from "node:assert/strict";
import { canModifyWorkspaceMember, isWorkspaceRole } from "./workspace-member-policy.ts";

test("workspace role choices are strict", () => {
  for (const value of ["admin", "editor", "viewer"]) assert.equal(isWorkspaceRole(value), true);
  for (const value of ["owner", "superadmin", "", "ADMIN"]) assert.equal(isWorkspaceRole(value), false);
});

test("managers cannot edit their own row", () => {
  assert.equal(canModifyWorkspaceMember({ isSelf: true, isProtected: false, workspaceRole: "admin" }), false);
});

test("tenant owners and admins have protected membership rows", () => {
  assert.equal(canModifyWorkspaceMember({ isSelf: false, isProtected: true, workspaceRole: "admin" }), false);
});

test("other ordinary members may be managed", () => {
  for (const workspaceRole of ["viewer", "editor", "admin"] as const) {
    assert.equal(canModifyWorkspaceMember({ isSelf: false, isProtected: false, workspaceRole }), true);
  }
});
