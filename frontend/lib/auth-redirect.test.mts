import assert from "node:assert/strict";
import test from "node:test";

import { authFormHref, safeInternalRedirect } from "./auth-redirect.ts";

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

test("invitation destination survives authentication without forwarding its credential", () => {
  const invitation = "/workspace-invite?token=invitation-123";
  const register = new URL(authFormHref("register", invitation), "https://bluedrive.invalid");
  assert.equal(register.pathname, "/register");
  const login = new URL(authFormHref("login", register.searchParams.get("next")), register.origin);
  assert.equal(login.pathname, "/login");
  assert.equal(safeInternalRedirect(login.searchParams.get("next")), "/workspace-invite");
  assert.equal(register.href.includes("invitation-123"), false);
  assert.equal(login.href.includes("invitation-123"), false);
  assert.equal(safeInternalRedirect("/admin-invite#uid=user&token=fixture"), "/admin-invite");
  assert.equal(safeInternalRedirect("/organization-invite#uid=user&token=fixture"), "/organization-invite");
  assert.equal(safeInternalRedirect("/workspace-invite/?token=fixture"), "/workspace-invite");
  assert.equal(safeInternalRedirect("/%77orkspace-invite?token=fixture"), "/workspace-invite");
});

test("auth continuation does not preserve external or recursive destinations", () => {
  for (const next of ["https://attacker.example", "//attacker.example", "/login?next=/register", undefined]) {
    const target = new URL(authFormHref("register", next), "https://bluedrive.invalid");
    assert.equal(target.searchParams.get("next"), "/drive");
  }
});
