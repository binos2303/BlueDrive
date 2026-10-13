import assert from "node:assert/strict";
import test from "node:test";

import { safeInternalRedirect } from "./auth-redirect.ts";

test("keeps safe same-origin application destinations", () => {
  assert.equal(
    safeInternalRedirect("/drive/recent?sort=name#files"),
    "/drive/recent?sort=name#files",
  );
});

test("falls back for external, protocol-relative, and backslash redirects", () => {
  for (const candidate of [
    "https://attacker.example/",
    "//attacker.example/",
    "///attacker.example/",
    "/\\attacker.example/",
    "/%5C%5Cattacker.example/",
  ]) {
    assert.equal(safeInternalRedirect(candidate), "/drive", candidate);
  }
});

test("avoids redirecting to the public auth forms", () => {
  assert.equal(safeInternalRedirect("/login?next=/drive"), "/drive");
  assert.equal(safeInternalRedirect("/register"), "/drive");
});
