import assert from "node:assert/strict";
import test from "node:test";
import { formatAdminRoleCount } from "./admin-permissions-format.ts";

test("platform role counts are labeled as accounts", () => {
  assert.equal(formatAdminRoleCount(1, "accounts"), "1 active account");
  assert.equal(formatAdminRoleCount(0, "accounts"), "0 active accounts");
});

test("workspace and tenant counts are assignments, never unique users", () => {
  assert.equal(formatAdminRoleCount(2, "assignments"), "2 active assignments");
  assert.equal(formatAdminRoleCount(1, "assignments"), "1 active assignment");
});

test("invalid server counts do not display a fake user number", () => {
  assert.equal(formatAdminRoleCount(-1, "accounts"), "0 active accounts");
  assert.equal(formatAdminRoleCount(Number.NaN, "assignments"), "0 active assignments");
});
