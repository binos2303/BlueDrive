import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { test as base, expect } from "@playwright/test";

const state = resolve("playwright/.auth/admin.json");
if (!existsSync(state)) throw new Error("Sign in with a platform admin test account first: npm run test:e2e:auth");
const apiURL = process.env.E2E_API_URL || "http://localhost:8000";
if (!["localhost", "127.0.0.1", "[::1]"].includes(new URL(apiURL).hostname)) throw new Error("Use a local test API only.");
const test = base.extend<{ readOnly: void }>({
  readOnly: [async ({ page }, use) => {
    const writes: string[] = [];
    await page.route("**/*", (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path.startsWith("/accounts/api/") && !["GET", "HEAD", "OPTIONS"].includes(request.method())) {
        writes.push(`${request.method()} ${path}`);
        return route.abort("blockedbyclient");
      }
      return route.continue();
    });
    await use();
    expect(writes, "Admin acceptance must not mutate real accounts or configuration").toEqual([]);
  }, { auto: true }],
});
test.use({ storageState: state });

const connected = [
  { route: "/admin", heading: "Dashboard", apis: ["overview"] },
  { route: "/admin/users", heading: "User Management", apis: ["users", "overview"] },
  { route: "/admin/organizations", heading: "Organization Management", apis: ["organizations"] },
  { route: "/admin/workspaces", heading: "Workspace Management", apis: ["workspaces"] },
  { route: "/admin/files", heading: "File Management", apis: ["files"] },
  { route: "/admin/permissions", heading: "Roles & Permissions", apis: ["permissions"] },
  { route: "/admin/activity", heading: "User Activity", apis: ["activity"] },
  { route: "/admin/audit", heading: "Admin Audit Logs", apis: ["audit"] },
  { route: "/admin/settings", heading: "System settings", apis: ["settings"] },
  { route: "/admin/infrastructure", heading: "System Health", apis: ["overview"] },
  { route: "/admin/infrastructure/quotas", heading: "Quota Management", apis: ["quota-plans", "quota-policy"] },
  { route: "/admin/infrastructure/quotas/users", heading: "Quota Management", apis: ["quotas", "quota-plans"] },
  { route: "/admin/infrastructure/quotas/workspaces", heading: "Quota Management", apis: ["quotas", "quota-plans"] },
  { route: "/admin/infrastructure/quotas/policies", heading: "Quota Management", apis: ["quota-plans", "quota-policy"] },
  { route: "/admin/infrastructure/quotas/capacity", heading: "Quota Management", apis: ["quotas/history", "quotas/configuration-history"] },
];

for (const item of connected) {
  test(`Live admin API and rendered page: ${item.route}`, async ({ page }, info) => {
    const errors: string[] = [];
    const crashes: string[] = [];
    page.on("pageerror", (error) => crashes.push(error.message));
    page.on("response", (response) => {
      const path = new URL(response.url()).pathname;
      if (path.startsWith("/accounts/api/") && response.status() >= 400) errors.push(`${response.status()} ${path}`);
    });
    const paths = ["me", ...["access", ...item.apis].map((path) => `admin/${path}`)];
    const responses = paths.map((path) => page.waitForResponse((r) => new URL(r.url()).pathname === `/accounts/api/${path}/` && r.request().method() === "GET"));
    await page.goto(item.route);
    for (const response of await Promise.all(responses)) expect(response.status()).toBe(200);
    await expect(page.getByRole("heading", { name: item.heading, exact: true })).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: /Loading|Verifying|Fetching|Checking/ })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath("admin-page.png"), fullPage: true, animations: "disabled" });
    await info.attach("Admin page", { path: info.outputPath("admin-page.png"), contentType: "image/png" });
    expect(errors).toEqual([]);
    expect(crashes).toEqual([]);
  });
}

const unavailable = [
  { route: "/admin/security/alerts", heading: "Security Alerts", status: "Detection pipeline not connected" },
  ...[["servers", "Servers"], ["storage", "Storage & Disks"], ["database", "PostgreSQL Database"], ["object-storage", "Object Storage"], ["alerts", "Alerts & Monitoring"]].map(([section, heading]) => ({ route: `/admin/infrastructure/${section}`, heading, status: "Unknown" })),
  { route: "/admin/backups", heading: "Backup Overview", status: "Backup service unavailable" },
  { route: "/admin/backups/jobs", heading: "Backup Jobs", status: "Unknown" },
  { route: "/admin/backups/history", heading: "Backup History", status: "Unknown records" },
  { route: "/admin/backups/policies", heading: "Backup Policies", status: "Policy controls are unavailable." },
  { route: "/admin/backups/restore", heading: "Restore Center", status: "Unknown" },
];
for (const item of unavailable) {
  test(`Live admin renders disconnected service honestly: ${item.route}`, async ({ page }, info) => {
    const access = page.waitForResponse((r) => new URL(r.url()).pathname === "/accounts/api/admin/access/");
    await page.goto(item.route);
    expect((await access).status()).toBe(200);
    await expect(page.getByRole("heading", { name: item.heading, exact: true })).toBeVisible();
    await expect(page.getByText(item.status, { exact: true }).first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath("unconnected-service.png"), fullPage: true, animations: "disabled" });
    await info.attach("Disconnected service", { path: info.outputPath("unconnected-service.png"), contentType: "image/png" });
  });
}

test("Live dedicated admin session cannot enter personal Drive APIs", async ({ page }) => {
  const me = await page.request.get(`${apiURL}/accounts/api/me/`);
  expect(me.status()).toBe(200);
  expect((await me.json()).is_platform_admin).toBe(true);
  const access = await page.request.get(`${apiURL}/accounts/api/admin/access/`);
  expect(access.status()).toBe(200);
  expect((await access.json()).allowed).toBe(true);
  expect((await page.request.get(`${apiURL}/drive/api/items/?view=drive`)).status()).toBe(403);
  await page.goto("/drive");
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
});

test("Live user sessions dialog opens and closes without revoking a session", async ({ page }, info) => {
  await page.goto("/admin/users");
  const button = page.getByRole("button", { name: "Sessions", exact: true }).first();
  await expect(button).toBeVisible();
  const response = page.waitForResponse((r) => new URL(r.url()).pathname === "/accounts/api/admin/sessions/");
  await button.click();
  expect((await response).status()).toBe(200);
  const dialog = page.getByRole("dialog", { name: /^Sessions · / });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Loading sessions…", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("admin-sessions.png"), animations: "disabled" });
  await info.attach("Sessions dialog", { path: info.outputPath("admin-sessions.png"), contentType: "image/png" });
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});

test("Live ordinary user is denied admin data and the admin console", async ({ browser }) => {
  const userState = resolve("playwright/.auth/user.json");
  expect(existsSync(userState), "Keep the ordinary test-user session to verify the access boundary").toBe(true);
  const context = await browser.newContext({ storageState: userState });
  try {
    const me = await context.request.get(`${apiURL}/accounts/api/me/`);
    expect(me.status()).toBe(200);
    expect((await me.json()).is_platform_admin).not.toBe(true);
    for (const path of ["access", "users", "quotas", "permissions"]) {
      expect((await context.request.get(`${apiURL}/accounts/api/admin/${path}/`)).status()).toBe(403);
    }
    const page = await context.newPage();
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "Administrator access required", exact: true })).toBeVisible();
  } finally { await context.close(); }
});

test("Live account directory search sends the query and returns the empty result", async ({ page }) => {
  await page.goto("/admin/users");
  const query = `ui-acceptance-no-match-${Date.now()}`;
  await page.getByRole("textbox", { name: "Search accounts", exact: true }).fill(query);
  const response = page.waitForResponse((r) => {
    const url = new URL(r.url());
    return url.pathname === "/accounts/api/admin/users/" && url.searchParams.get("q") === query;
  });
  await page.getByRole("textbox", { name: "Search accounts", exact: true }).press("Enter");
  const result = await response;
  expect(result.status()).toBe(200);
  expect((await result.json()).count).toBe(0);
  await expect(page.getByRole("status").filter({ hasText: /Loading/ })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "User Management", exact: true })).toBeVisible();
});

test("Live quota edit controls match the authenticated admin capability", async ({ page }, info) => {
  const access = await page.request.get(`${apiURL}/accounts/api/admin/access/`);
  expect(access.status()).toBe(200);
  const capability = (await access.json()).can_manage_admins;
  const directory = page.waitForResponse((r) => new URL(r.url()).pathname === "/accounts/api/admin/quotas/");
  await page.goto("/admin/infrastructure/quotas/users");
  expect((await directory).status()).toBe(200);
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeEnabled();
  const manage = page.getByRole("button", { name: "Manage", exact: true });
  if (capability) {
    await manage.first().click();
    const dialog = page.getByRole("dialog", { name: "Assign storage plan", exact: true });
    await expect(dialog.getByRole("button", { name: "Assign plan", exact: true })).toBeDisabled();
    await page.screenshot({ path: info.outputPath("live-quota-dialog.png"), animations: "disabled" });
    await info.attach("Quota dialog", { path: info.outputPath("live-quota-dialog.png"), contentType: "image/png" });
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
  } else {
    await expect(manage).toHaveCount(0);
    await expect(page.getByText("View only", { exact: true }).first()).toBeVisible();
  }
});

test("Live admin theme, navigation drawer and Back preserve the current section", async ({ page, isMobile }, info) => {
  await page.goto("/admin");
  const toggle = page.getByRole("button", { name: "Toggle light or dark theme", exact: true });
  await expect(toggle).toBeVisible();
  const original = await page.locator("html").getAttribute("data-theme");
  await toggle.click();
  const changed = original === "dark" ? "light" : "dark";
  await expect(page.locator("html")).toHaveAttribute("data-theme", changed);
  if (isMobile) await page.getByRole("button", { name: "Open navigation", exact: true }).click();
  const nav = page.getByRole("navigation", { name: "Admin navigation", exact: true });
  await nav.getByRole("button", { name: "Security", exact: true }).click();
  await nav.getByRole("link", { name: "Roles & Permissions", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/permissions$/);
  await expect(page.getByRole("heading", { name: "Roles & Permissions", exact: true })).toBeVisible();
  if (isMobile) await expect(nav).not.toBeVisible();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", changed);
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeEnabled();
  await page.screenshot({ path: info.outputPath("admin-theme-navigation.png"), fullPage: true, animations: "disabled" });
  await info.attach("Theme and navigation", { path: info.outputPath("admin-theme-navigation.png"), contentType: "image/png" });
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
});
