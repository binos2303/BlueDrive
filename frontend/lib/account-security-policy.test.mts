import test from "node:test";
import assert from "node:assert/strict";
import { passwordChangeIssue, mayHaveNextPage } from "./account-security-policy.ts";

test("requires current and new password inputs", () => {
  assert.match(passwordChangeIssue("", "strong-password", "strong-password") || "", /Complete/);
});
test("rejects mismatched confirmation without submitting", () => {
  assert.match(passwordChangeIssue("old", "next", "different") || "", /match/);
});
test("rejects password identical to current value", () => {
  assert.match(passwordChangeIssue("abc", "abc", "abc") || "", /different/);
});
test("defers password strength to Django validation", () => {
  assert.equal(passwordChangeIssue("old", "new", "new"), null);
});
test("determines pagination from server count", () => {
  assert.equal(mayHaveNextPage(21, 1, 20), true);
  assert.equal(mayHaveNextPage(21, 2, 20), false);
});
