import test from "node:test";
import assert from "node:assert/strict";
import { buildAdminFileQuery } from "./admin-file-query.ts";

test("inventory query preserves filters and stable pagination", () => {
  const q = new URLSearchParams(buildAdminFileQuery({
    query: "  sales & ops  ", scope: "organization", status: "trash", sort: "newest", page: 3,
  }));
  assert.equal(q.get("q"), "sales & ops");
  assert.equal(q.get("scope"), "organization");
  assert.equal(q.get("status"), "trash");
  assert.equal(q.get("page"), "3");
  assert.equal(q.get("type"), "all");
});

test("inventory query limits user input", () => {
  const q = new URLSearchParams(buildAdminFileQuery({
    query: "a".repeat(150), scope: "all", status: "active", sort: "updated", page: NaN,
  }));
  assert.equal(q.get("q")?.length, 120);
  assert.equal(q.get("page"), "1");
});
