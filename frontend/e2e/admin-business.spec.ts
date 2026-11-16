import { test, expect, type MockApi } from "./mocked-api";

const member = { id: 7, username: "review_member", email: "review@example.invalid", is_active: true, is_staff: false, is_superuser: false, last_login: null, date_joined: "2026-01-01T00:00:00Z", recently_online: false };
const overview = {
  users: { total: 1, active: 1, inactive: 0, platform_admins: 1, recently_seen: 0 },
  organizations: { total: 0, active: 0 }, workspaces: { total: 0, active: 0, organization: 0, personal: 0 },
  files: { total: 0, metadata_bytes: 0, in_trash: 0 }, health: { api: "responding", database: "responding", storage: "not_monitored" },
  uploads: { pending_jobs: 3, processing_jobs: 2, failed_jobs: 4, stale_processing_jobs: 1, verifying_uploads: 2, scanning_uploads: 1, oldest_active_job_at: "2026-11-08T01:00:00Z" },
};

function adminFixtures(api: MockApi) {
  api.admin = true;
  api.override("/accounts/api/admin/overview/", (route) => route.fulfill({ json: overview }));
  api.override("/accounts/api/admin/users/", (route) => route.fulfill({ json: { count: 1, page: 1, page_size: 20, sort: "recent_signin", results: [member] } }));
  for (const path of ["organizations", "workspaces"]) api.override(`/accounts/api/admin/${path}/`, (route) => route.fulfill({ json: { count: 0, page: 1, page_size: 20, results: [] } }));
  api.override("/accounts/api/admin/files/", (route) => route.fulfill({ json: { count: 0, page: 1, page_size: 20, permissions: { can_manage_files: true }, summary: { active: 0, trash: 0, active_metadata_bytes: 0 }, results: [] } }));
  api.override("/accounts/api/admin/permissions/", (route) => route.fulfill({ json: { roles: [], notes: ["Existing authorization policies"] } }));
  api.override("/accounts/api/admin/storage/platform/live/", (route) => route.fulfill({ json: {
    source: "seaweedfs_master", observed_at: null, master_online: false, s3_gateway_responding: false,
    nodes: ["volume", "volume2", "volume3"].map((id) => ({ id, address: "", online: false, datacenter: "", rack: "", max_slots: 0, free_slots: 0, volumes: 0, stored_bytes: null })),
    online_nodes: 0, volume_slots: 0, free_slots: 0, used_volume_slots: 0, stored_volume_bytes: null,
    physical_disk_bytes_available: null, error_code: "platform_master_unavailable", routing_enabled: false, binding_ready: false, binding_revision: null,
  } }));
  api.override("/accounts/api/admin/settings/", (route) => route.fulfill({ json: {
    display_name: "Platform console", revision: 0, can_edit: true, updated_at: null,
    effective_security: { session_cookie_age_seconds: 3600, expire_at_browser_close: false, session_cookie_secure: false, csrf_cookie_secure: false, admin_audit: "enforced_for_supported_actions", maintenance_mode: "not_configured" },
  } }));
}

const routes = [
  ["/admin", "Dashboard"], ["/admin/users", "User Management"], ["/admin/users/audit", "Admin Audit Logs"],
  ["/admin/organizations", "Organization Management"], ["/admin/workspaces", "Workspace Management"],
  ["/admin/files", "File Management"], ["/admin/permissions", "Roles & Permissions"],
  ["/admin/activity", "User Activity"], ["/admin/audit", "Admin Audit Logs"], ["/admin/settings", "System settings"],
  ["/admin/infrastructure", "System Health"],
  ...["", "/users", "/workspaces", "/policies", "/capacity"].map((section) => [`/admin/infrastructure/quotas${section}`, "Quota Management"]),
  ["/admin/security/alerts", "Security Alerts"], ["/admin/infrastructure/topology", "Platform storage"],
  ...[["servers", "Servers"], ["storage", "Storage & Disks"], ["database", "PostgreSQL Database"], ["object-storage", "Object Storage"], ["alerts", "Alerts & Monitoring"]].map(([path, title]) => [`/admin/infrastructure/${path}`, title]),
  ...[["", "Backup Overview"], ["/jobs", "Backup Jobs"], ["/history", "Backup History"], ["/policies", "Backup Policies"], ["/restore", "Restore Center"]].map(([path, title]) => [`/admin/backups${path}`, title]),
];

for (const [path, title] of routes) {
  test(`Admin route inventory ${path}`, async ({ page, api }, info) => {
    adminFixtures(api);
    const crashes: string[] = [];
    page.on("pageerror", (error) => crashes.push(error.message));
    await page.goto(path);
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: /Loading|Verifying|Fetching|Checking/ })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath("admin-route.png"), fullPage: true });
    expect(crashes).toEqual([]);
  });
}

test("Admin navigation only promotes available capabilities and exposes upload operations", async ({ page, api, isMobile }, info) => {
  adminFixtures(api);
  await page.goto("/admin");
  await expect(page.getByRole("status", { name: "Loading platform overview", exact: true })).toHaveCount(0);
  await expect(page.getByText("Stale upload processing needs attention.", { exact: true })).toBeVisible();
  const processing = page.getByRole("region", { name: "Upload processing", exact: true });
  await expect(processing.getByText("Queued jobs", { exact: true })).toBeVisible();
  if (isMobile) await page.getByRole("button", { name: /Open.*navigation/i }).click();
  for (const group of ["Security", "Infrastructure", "System"]) {
    const button = page.getByRole("button", { name: group, exact: true });
    if (await button.getAttribute("aria-expanded") !== "true") await button.click();
  }
  const navigation = page.getByRole("navigation", { name: "Admin navigation", exact: true });
  await expect(navigation.getByRole("link", { name: "System Health", exact: true })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Settings", exact: true })).toBeVisible();
  for (const name of ["Backups", "Storage Topology", "Security Alerts"]) await expect(navigation.getByRole("link", { name, exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("admin-navigation.png"), fullPage: true });
});

test("System Health can recover after a failed load without claiming worker uptime", async ({ page, api }, info) => {
  adminFixtures(api);
  let unavailable = true;
  api.override("/accounts/api/admin/overview/", (route) => unavailable
    ? route.fulfill({ status: 503, json: { detail: "Overview temporarily unavailable" } })
    : route.fulfill({ json: overview }));
  await page.goto("/admin/infrastructure");
  await expect(page.getByRole("alert").filter({ hasText: "Overview temporarily unavailable" })).toBeVisible();
  unavailable = false;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByText("Stale upload processing needs attention.", { exact: true })).toBeVisible();
  await expect(page.getByText("Overview temporarily unavailable", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Upload processing", exact: true })).toContainText("does not prove that a worker is offline");
  await page.screenshot({ path: info.outputPath("admin-health.png"), fullPage: true });
  await page.getByText("Oldest active job update", { exact: true }).scrollIntoViewIfNeeded();
  await expect(page.getByText("Oldest active job update", { exact: true })).toBeInViewport();
  await page.screenshot({ path: info.outputPath("admin-health-scrolled.png") });
});

test("Pending user suspension locks its dialog and preserves the reason on failure", async ({ page, api }) => {
  adminFixtures(api);
  let finish: () => void = () => {};
  const ready = new Promise<void>((resolve) => { finish = resolve; });
  api.override("POST /accounts/api/admin/users/7/suspend/", async (route) => { await ready; await route.fulfill({ status: 503, json: { detail: "Account action failed fixture" } }); });
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "Suspend", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Suspend review_member?", exact: true });
  const reason = dialog.getByLabel("Reason (8–500 characters)");
  await reason.fill("Investigate reported account misuse");
  try {
    await dialog.getByRole("button", { name: "Confirm", exact: true }).click();
    await expect(reason).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Close dialog", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    finish();
    await expect(dialog.getByRole("alert")).toContainText("Account action failed fixture");
    await expect(reason).toHaveValue("Investigate reported account misuse");
    await expect(reason).toBeEnabled();
  } finally { finish(); }
});

test("Pending invitation is submitted once and cannot close or change fields", async ({ page, api }) => {
  adminFixtures(api);
  let finish: () => void = () => {};
  let sent = 0;
  const ready = new Promise<void>((resolve) => { finish = resolve; });
  api.override("POST /accounts/api/admin/administrators/invite/", async (route) => { sent += 1; await ready; await route.fulfill({ status: 503, json: { detail: "Mock email delivery failed" } }); });
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "Platform Admins", exact: true }).click();
  await page.getByRole("button", { name: "Add Administrator", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add Platform Administrator", exact: true });
  await dialog.getByLabel("Username", { exact: true }).fill("review_admin");
  await dialog.getByLabel("Email", { exact: true }).fill("review-admin@example.invalid");
  await dialog.getByLabel("Reason (8–500 characters)").fill("Invite a dedicated operations account");
  try {
    await dialog.locator("form").evaluate((form) => { form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    await expect(dialog.getByLabel("Username", { exact: true })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Close dialog", exact: true })).toBeDisabled();
    await expect.poll(() => sent).toBe(1);
    finish();
    await expect(dialog.getByRole("alert")).toContainText("Mock email delivery failed");
    expect(sent).toBe(1);
  } finally { finish(); }
});

test("Session errors can retry and pending revocation locks both dialogs", async ({ page, api }) => {
  adminFixtures(api);
  let unavailable = true;
  let finish: () => void = () => {};
  const ready = new Promise<void>((resolve) => { finish = resolve; });
  api.override("/accounts/api/admin/sessions/", (route) => unavailable ? route.fulfill({ status: 503, json: { detail: "Session inventory unavailable fixture" } }) : route.fulfill({ json: {
    count: 1, page: 1, page_size: 20, tracking_note: "Observed sessions only", results: [{ id: "session-review", user_id: 7, username: "review_member", user_agent: "Review browser", started_at: "2026-11-08T00:00:00Z", last_seen_at: "2026-11-08T00:00:00Z", expires_at: "2099-01-01T00:00:00Z", recently_online: false, can_revoke: true }],
  } }));
  api.override("POST /accounts/api/admin/sessions/session-review/revoke/", async (route) => { await ready; await route.fulfill({ status: 503, json: { detail: "Revocation failed fixture" } }); });
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "Sessions", exact: true }).click();
  const parent = page.getByRole("dialog", { name: "Sessions · review_member", exact: true });
  await expect(parent.getByRole("alert")).toContainText("Session inventory unavailable fixture");
  unavailable = false;
  await parent.getByRole("button", { name: "Retry sessions", exact: true }).click();
  await parent.getByRole("button", { name: "Revoke", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Revoke observed session?", exact: true });
  await dialog.getByLabel("Reason (8–500 characters)").fill("User requested this session logout");
  try {
    await dialog.getByRole("button", { name: "Revoke session", exact: true }).click();
    await expect(dialog.getByRole("button", { name: "Close dialog", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    finish();
    await expect(dialog.getByRole("alert")).toContainText("Revocation failed fixture");
  } finally { finish(); }
});
