import assert from "node:assert/strict";
import test from "node:test";
import { canOpenShareManagement } from "./share-policy.ts";

test("share UI requires at least one owned item", () => {
  assert.equal(canOpenShareManagement([]), false);
  assert.equal(canOpenShareManagement([{ owner: "Me" }]), true);
});

test("workspace editors cannot grant access to another member's item", () => {
  assert.equal(canOpenShareManagement([{ owner: "Alice", canManage: true }]), false);
  assert.equal(canOpenShareManagement([{ owner: "Me" }, { owner: "Alice", canManage: true }]), false);
});

test("read-only or mixed selections cannot grant direct shares", () => {
  assert.equal(canOpenShareManagement([{ owner: "Me", canManage: false }]), false);
  assert.equal(canOpenShareManagement([{ owner: "Me" }, { owner: "Me", canManage: true }]), true);
});
