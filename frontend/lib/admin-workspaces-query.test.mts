import test from "node:test";
import assert from "node:assert/strict";
import { buildAdminWorkspaceQuery, countAssignedMembers } from "./admin-workspaces-query.ts";

test("workspace listing uses deterministic sort and scope", () => {
  const query = new URLSearchParams(buildAdminWorkspaceQuery({
    query: " Blue & Green ", scope: "organization", sort: "name_desc", page: 3,
  }));
  assert.equal(query.get("q"), "Blue & Green");
  assert.equal(query.get("scope"), "organization");
  assert.equal(query.get("sort"), "name_desc");
  assert.equal(query.get("page"), "3");
});

test("workspace query constrains long searches and invalid page", () => {
  const query = new URLSearchParams(buildAdminWorkspaceQuery({
    query: "x".repeat(300), scope: "all", sort: "newest", page: -2,
  }));
  assert.equal(query.get("q")?.length, 100);
  assert.equal(query.get("page"), "1");
});

test("member counts include only explicit role assignments", () => {
  assert.equal(countAssignedMembers({ admin: 2, editor: 3, viewer: 4 }), 9);
  assert.equal(countAssignedMembers({ admin: 0, editor: 0, viewer: 0 }), 0);
});
