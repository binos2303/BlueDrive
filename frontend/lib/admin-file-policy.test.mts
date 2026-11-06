import test from "node:test";
import assert from "node:assert/strict";
import { actionsForAdminFile, canSubmitAdminFileAction } from "./admin-file-policy.ts";

test("ordinary Platform Admin can only inspect metadata", () => {
  assert.deepEqual(actionsForAdminFile("active", false), []);
  assert.deepEqual(actionsForAdminFile("trash", false), []);
});

test("admin operations are derived from lifecycle", () => {
  assert.deepEqual(actionsForAdminFile("active", true), ["trash"]);
  assert.deepEqual(actionsForAdminFile("trash", true), ["restore", "purge"]);
});

test("reason is required and bounded", () => {
  for (const reason of ["", "short", "x".repeat(501)]) {
    assert.equal(canSubmitAdminFileAction({ action: "restore", reason, fileName: "a.txt", confirmation: "" }), false);
  }
  assert.equal(canSubmitAdminFileAction({ action: "trash", reason: " Review approved ", fileName: "a.txt", confirmation: "" }), true);
});

test("purge requires exact typed confirmation", () => {
  const input = { action: "purge" as const, reason: "Security review required", fileName: "Report Final.PDF", confirmation: "report final.pdf" };
  assert.equal(canSubmitAdminFileAction(input), false);
  assert.equal(canSubmitAdminFileAction({ ...input, confirmation: input.fileName }), true);
});
