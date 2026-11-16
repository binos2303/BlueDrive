import assert from "node:assert/strict";

// Read-only production route checks. Start `next start` separately; no API cookies are sent.
const base = process.argv[2] || "http://127.0.0.1:3107";
const routes = [
  "/login", "/register", "/admin-invite", "/workspace-invite",
  "/account/settings", "/account/settings?section=security", "/account/settings?section=privacy", "/account/settings?section=connections", "/account/upgrade",
  "/drive", "/drive/recent", "/drive/starred", "/drive/trash", "/drive/shared", "/drive/shared-by-me", "/drive/folders/1",
  ...["files", "recent", "starred", "trash", "folders/1", "members", "activity"].map((view) => `/drive/workspaces/audit-workspace/${view}`),
  "/organization/admin", "/admin", "/admin/users", "/admin/organizations", "/admin/workspaces", "/admin/files", "/admin/permissions", "/admin/activity", "/admin/audit", "/admin/security/alerts", "/admin/settings",
  "/admin/infrastructure", "/admin/infrastructure/topology",
  ...["servers", "storage", "database", "object-storage", "alerts", "quotas", "quotas/users", "quotas/workspaces", "quotas/policies", "quotas/capacity"].map((view) => `/admin/infrastructure/${view}`),
  ...["", "/jobs", "/history", "/policies", "/restore"].map((view) => `/admin/backups${view}`),
];

for (const route of routes) {
  const response = await fetch(base + route, { redirect: "manual" });
  assert.equal(response.status, 200, route);
  const html = await response.text();
  const script = html.indexOf("securedrive:theme-preference:v1");
  assert.ok(script > 0 && script < html.indexOf("<body"), `${route}: theme initializes before the body`);
}

let httpRedirects = 0;
let streamedRedirects = 0;
for (const [route, target] of [
  ["/", "/login"], ["/account/profile", "/account/settings?section=security"],
  ["/admin/teams", "/admin/workspaces"], ["/admin/infrastructure/quotas/teams", "/admin/infrastructure/quotas/workspaces"],
  ["/admin/users/audit", "/admin/audit"], ["/drive/workspaces/audit-workspace", "/drive/workspaces/audit-workspace/files"],
]) {
  const response = await fetch(base + route, { redirect: "manual" });
  if (response.status === 307) {
    const location = new URL(response.headers.get("location"), base);
    assert.equal(location.pathname + location.search, target, route);
    httpRedirects++;
  } else {
    // Next can have committed a streamed 200 before a nested route redirects.
    assert.equal(response.status, 200, route);
    assert.ok((await response.text()).includes(`NEXT_REDIRECT;replace;${target};307;`), route);
    streamedRedirects++;
  }
}

let httpNotFound = 0;
let streamedNotFound = 0;
for (const route of [
  "/account/support",
  "/admin/infrastructure/invalid-section", "/admin/infrastructure/__proto__", "/admin/infrastructure/constructor",
  "/drive/folders/invalid", "/drive/workspaces/audit-workspace/unknown", "/drive/workspaces/audit-workspace/folders/invalid",
]) {
  const response = await fetch(base + route, { redirect: "manual" });
  if (response.status === 404) httpNotFound++;
  else {
    assert.equal(response.status, 200, route);
    assert.ok((await response.text()).includes("NEXT_HTTP_ERROR_FALLBACK;404"), `${route}: not-found boundary`);
    streamedNotFound++;
  }
}

for (const [mode, other] of [["login", "register"], ["register", "login"]]) {
  const response = await fetch(`${base}/${mode}?next=${encodeURIComponent("/workspace-invite?token=ui-audit-fixture")}`);
  assert.ok((await response.text()).includes(`href="/${other}?next=%2Fworkspace-invite%3Ftoken%3Dui-audit-fixture"`), `${mode}: invitation continuation`);
}

console.log(JSON.stringify({
  routeDelivery: routes.length, httpRedirects, streamedRedirects, httpNotFound, streamedNotFound,
  authContinuation: 2, prePaintTheme: "present before body on all checked routes",
  limits: "HTTP HTML/RSC signals only; no browser hydration, rendering or authenticated API execution",
}, null, 2));
