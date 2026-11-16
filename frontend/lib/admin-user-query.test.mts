import test from "node:test";
import assert from "node:assert/strict";
import { buildAdminUserQuery } from "./admin-user-query.ts";

test("encodes all supported server-side sorting and filtering controls", () => {
  for (const sort of ["recent_signin", "oldest_signin", "newest", "oldest", "name_asc", "name_desc"] as const) {
    const query = new URLSearchParams(buildAdminUserQuery({
      scope: "users", status: "active", sort, query: " alice@example.test ", page: 2,
    }));
    assert.equal(query.get("sort"), sort);
    assert.equal(query.get("scope"), "users");
    assert.equal(query.get("status"), "active");
    assert.equal(query.get("q"), "alice@example.test");
    assert.equal(query.get("page"), "2");
  }
});

test("normalizes invalid page numbers and truncates long searches", () => {
  const query = new URLSearchParams(buildAdminUserQuery({
    scope: "admins", status: "inactive", sort: "newest", query: "x".repeat(250), page: 0,
  }));
  assert.equal(query.get("page"), "1");
  assert.equal(query.get("q")?.length, 100);
});

test("search special characters are properly URL encoded", () => {
  const query = new URLSearchParams(buildAdminUserQuery({
    scope: "users", status: "all", sort: "name_asc", query: "A&B+C@example.test", page: 1,
  }));
  assert.equal(query.get("q"), "A&B+C@example.test");
});
