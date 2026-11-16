import { test, expect } from "./mocked-api";

test("Recent empty state explains the seven day file window", async ({ page, api }, info) => {
  api.items = [];
  await page.goto("/drive/recent");
  await expect(page.getByText("Files opened or updated in the last 7 days appear here.", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Recent timeline", exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("recent-seven-days.png") });
});

test("User surfaces no longer expose Support or its page", async ({ page }) => {
  await page.goto("/drive");
  await page.getByRole("button", { name: "Account actions for ui_test", exact: true }).click();
  await expect(page.getByRole("menuitem", { name: "Support", exact: true })).toHaveCount(0);
  await expect(page.getByRole("menuitem", { name: "Settings", exact: true })).toBeVisible();
  for (const route of ["/account/settings", "/account/upgrade", "/login", "/register"]) {
    await page.goto(route);
    await expect(page.locator('a[href="/account/support"]')).toHaveCount(0);
    await expect(page.getByText("Contact support", { exact: true })).toHaveCount(0);
  }
  const removed = await page.goto("/account/support");
  expect(removed?.status()).toBe(404);
});

test("Timeline is absent from Recent and appears only in Workspace Activity log", async ({ page, api, isMobile }, info) => {
  api.items[0].modified = new Date().toISOString();
  api.override("/accounts/api/workspaces/workspace-a/activity/", (route) => route.fulfill({ json: { events: [
    { id: 1, username: "workspace_member", action: "UPLOAD", actionLabel: "Upload", description: "Workspace event fixture", createdAt: new Date().toISOString(), metadata: {} },
  ] } }));
  for (const route of ["/drive/recent", "/drive/workspaces/workspace-a/recent"]) {
    await page.goto(route);
    await expect(page.getByRole("checkbox", { name: "Select Annual report 2024.txt", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recent timeline", exact: true })).toHaveCount(0);
  }
  const recent = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname === "/drive/api/items/" && url.searchParams.get("view") === "timeline";
  });
  if (isMobile) await page.getByRole("button", { name: "Open navigation", exact: true }).click();
  await page.getByRole("navigation", { name: "Workspace navigation" }).getByRole("link", { name: "Activity log", exact: true }).click();
  expect((await recent).headers()["x-workspace-id"]).toBe("workspace-a");
  await expect(page.getByRole("heading", { name: "Workspace activity log", exact: true })).toBeVisible();
  const chart = page.getByRole("figure", { name: "Recent timeline", exact: true });
  await expect(chart).toBeVisible();
  await expect(chart.getByRole("listitem")).toHaveCount(14);
  await expect(chart.getByRole("listitem").last()).toHaveAttribute("title", /: 1 items$/);
  await expect(page.getByText("Workspace event fixture", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth))).toBeLessThanOrEqual(page.viewportSize()!.width);
  if (isMobile) {
    await chart.getByRole("region").evaluate((element) => { element.scrollLeft = element.scrollWidth; });
    await expect(chart.getByRole("listitem").last()).toBeInViewport();
  }
  await page.screenshot({ path: info.outputPath("workspace-activity-timeline.png"), fullPage: true, animations: "disabled" });
});

test("Workspace chart failure preserves activity events and Refresh retries it", async ({ page, api }) => {
  api.override("/accounts/api/workspaces/workspace-a/activity/", (route) => route.fulfill({ json: { events: [
    { id: 1, username: "workspace_member", action: "UPLOAD", actionLabel: "Upload", description: "Keep this activity visible", createdAt: new Date().toISOString(), metadata: {} },
  ] } }));
  api.override("/drive/api/items/", (route) => route.fulfill({ status: 503, json: { detail: "Recent files unavailable" } }));
  await page.goto("/drive/workspaces/workspace-a/activity");
  await expect(page.getByRole("alert").filter({ hasText: "Recent file timeline could not be loaded" })).toBeVisible();
  await expect(page.getByText("Keep this activity visible", { exact: true })).toBeVisible();
  await expect(page.getByRole("figure", { name: "Recent timeline", exact: true })).toHaveCount(0);
  api.override("/drive/api/items/", (route) => route.fulfill({ json: { items: api.items } }));
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("figure", { name: "Recent timeline", exact: true })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "Recent file timeline could not be loaded" })).toHaveCount(0);
});

test("Denied workspace activity does not fetch or show the timeline", async ({ page, api }) => {
  api.override("/accounts/api/workspaces/workspace-a/activity/", (route) => route.fulfill({ status: 403, json: { detail: "Workspace manager access required" } }));
  await page.goto("/drive/workspaces/workspace-a/activity");
  await expect(page.getByRole("alert").filter({ hasText: "Activity log could not be loaded" })).toBeVisible();
  await expect(page.getByRole("figure", { name: "Recent timeline", exact: true })).toHaveCount(0);
  expect(api.requests.filter((request) => request.path === "/drive/api/items/")).toHaveLength(0);
});

test("Admin file rows keep long MIME text compact and action labels on one line", async ({ page, api }, info) => {
  api.admin = true;
  const mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  const file = { id: 301, name: "huhu (2).docx", size_bytes: 35800, mime_type: mime,
    owner: { id: 3, username: "securedrive_test_with_a_long_username" }, scope: "my_drive", organization: null,
    workspace: { id: "workspace-test", name: "General" }, folder: null, lifecycle: "active", version_state: "available",
    current_version: 1, version_count: 1, is_encrypted: true, created_at: "2026-11-07T02:24:00Z", updated_at: "2026-11-07T02:24:00Z", deleted_at: null };
  api.override("/accounts/api/admin/files/", (route) => route.fulfill({ json: {
    count: 2, page: 1, page_size: 20, summary: { active: 1, trash: 1, active_metadata_bytes: 35800 },
    permissions: { can_manage_files: true }, results: [file, { ...file, id: 302, name: "File in Trash.docx", lifecycle: "trash", deleted_at: "2026-11-07T03:00:00Z" }],
  } }));
  await page.goto("/admin/files");
  await expect(page.getByRole("button", { name: "View metadata for huhu (2).docx", exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath("admin-file-metadata.png"), animations: "disabled" });
  for (const row of await page.locator("tbody tr").all()) {
    const mimeText = row.getByText(mime, { exact: true });
    const mimeBox = await mimeText.boundingBox();
    expect(mimeBox).not.toBeNull();
    expect(mimeBox!.height).toBeLessThanOrEqual(20);
    const actions = row.locator("td").last();
    for (const button of await actions.getByRole("button").all()) {
      await button.scrollIntoViewIfNeeded();
      const bounds = await button.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.height).toBeLessThanOrEqual(48);
      expect(bounds!.width).toBeGreaterThanOrEqual(48);
      const cell = (await actions.boundingBox())!;
      expect(bounds!.x).toBeGreaterThanOrEqual(cell.x);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(cell.x + cell.width);
    }
  }
  await page.screenshot({ path: info.outputPath("admin-file-actions.png"), animations: "disabled" });
  await page.getByRole("button", { name: "Move to Trash huhu (2).docx", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Move file to Trash?", exact: true });
  await expect(dialog.getByRole("button", { name: "Move to Trash", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await page.setViewportSize({ width: 1920, height: 900 });
  await page.screenshot({ path: info.outputPath("admin-file-wide.png"), animations: "disabled" });
});

test("Drive list keyboard selection, move dialog focus and Escape", async ({ page }, info) => {
  await page.goto("/drive");
  const checkbox = page.getByRole("checkbox", { name: "Select Annual report 2024.txt", exact: true });
  await checkbox.focus();
  await page.keyboard.press("Space");
  await expect(checkbox).toBeChecked();
  const toolbar = page.getByRole("toolbar", { name: "Selected file actions" });
  await toolbar.getByRole("button", { name: "Move", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Move 1 item", exact: true });
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate((el) => el.matches(":modal"))).toBe(true);
  for (let i = 0; i < 9; i++) {
    await page.keyboard.press("Tab");
    // Chrome may hand Tab to browser chrome; background app controls must stay inert.
    expect(await dialog.evaluate((el) => el.contains(document.activeElement) || document.activeElement === document.body)).toBe(true);
  }
  await page.screenshot({ path: info.outputPath("move-dialog.png") });
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(checkbox).toBeChecked();
});

test("Grid nested buttons do not open or select the card", async ({ page }, info) => {
  await page.goto("/drive");
  await page.getByRole("button", { name: "Grid view", exact: true }).click();
  const card = page.locator('article[data-drive-item-id="101"]');
  await expect(card).toBeVisible();
  const star = card.getByRole("button", { name: "Add Annual report 2024.txt to Starred", exact: true });
  await star.focus();
  await page.keyboard.press("Enter");
  await expect(card.getByRole("button", { name: "Remove Annual report 2024.txt from Starred", exact: true })).toBeVisible();
  await expect(card).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await card.getByRole("button", { name: "Actions for Annual report 2024.txt", exact: true }).focus();
  await page.keyboard.press("Space");
  await expect(page.getByRole("menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(card.getByRole("button", { name: "Actions for Annual report 2024.txt", exact: true })).toBeFocused();
  await expect(card).toHaveAttribute("aria-pressed", "false");
  await card.focus();
  await page.keyboard.press("Space");
  await expect(card).toHaveAttribute("aria-pressed", "true");
  await page.screenshot({ path: info.outputPath("drive-grid.png"), fullPage: true, animations: "disabled" });
});

test("Bulk sharing keeps an API error and input inside the modal", async ({ page, api }) => {
  api.override("/drive/api/items/share/", (route) => route.fulfill({ status: 503, json: { detail: "Sharing temporarily unavailable. Please retry." } }));
  await page.goto("/drive");
  await page.getByRole("checkbox", { name: "Select Annual report 2024.txt", exact: true }).check();
  await page.getByRole("checkbox", { name: "Select Budget review 2025.txt", exact: true }).check();
  await page.getByRole("toolbar", { name: "Selected file actions" }).getByRole("button", { name: "Share", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Share 2 items", exact: true });
  await dialog.getByLabel("Email address").fill("recipient@example.invalid");
  await dialog.getByRole("button", { name: "Share", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Sharing temporarily unavailable");
  await expect(dialog.getByLabel("Email address")).toHaveValue("recipient@example.invalid");
});

test("Privacy distinguishes failed loads from empty data and retries", async ({ page, api }, info) => {
  api.override("/accounts/api/me/activity/", (route) => route.fulfill({ status: 503, json: { detail: "Activity temporarily unavailable" } }));
  api.override("/accounts/api/me/search-history/", (route) => route.fulfill({ status: 503, json: { detail: "Search temporarily unavailable" } }));
  await page.goto("/account/settings?section=privacy");
  await expect(page.getByRole("button", { name: "Retry activity", exact: true })).toBeVisible();
  await expect(page.getByText("No activity recorded yet.", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Retry search history", exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath("privacy-errors.png"), fullPage: true });
});

test("Privacy open date ranges and URL refresh preserve the section", async ({ page }) => {
  await page.goto("/account/settings?section=privacy");
  await expect(page.getByText("Early fixture event", { exact: true })).toBeVisible();
  await page.getByLabel("From", { exact: true }).fill("2026-11-02");
  await expect(page.getByText("Early fixture event", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Later fixture event", { exact: true })).toBeVisible();
  await page.getByLabel("To", { exact: true }).fill("2026-11-07");
  await expect(page.getByText("Later fixture event", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/section=privacy/);
  await expect(page.getByRole("heading", { name: "Privacy", exact: true })).toBeVisible();
  await expect(page.getByText("Later fixture event", { exact: true })).toBeVisible();
});

test("Light and dark layouts fit viewport and expose readable status tokens", async ({ page }, info) => {
  await page.goto("/drive");
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => localStorage.setItem("securedrive:theme-preference:v1", value), theme);
    await page.reload();
    await expect(page.getByRole("checkbox", { name: "Select Annual report 2024.txt", exact: true })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`drive-${theme}.png`), fullPage: true });
  }
});

test("Login to registration preserves the invitation continuation", async ({ page }, info) => {
  await page.goto("/login?next=%2Fworkspace-invite%3Ftoken%3Dfixture");
  await page.getByRole("link", { name: "Create account", exact: true }).click();
  await expect(page).toHaveURL(/\/register\?next=/);
  expect(new URL(page.url()).searchParams.get("next")).toBe("/workspace-invite?token=fixture");
  await page.screenshot({ path: info.outputPath("register.png"), fullPage: true });
});

test("Quota mutation errors stay in the modal and failed filters hide old rows", async ({ page, api }, info) => {
  api.admin = true;
  api.override("PATCH /accounts/api/admin/quotas/quota-test/", (route) => route.fulfill({ status: 503, json: { detail: "Quota save temporarily unavailable" } }));
  await page.goto("/admin/infrastructure/quotas/users");
  await page.getByRole("button", { name: "Manage", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Assign storage plan", exact: true });
  await dialog.getByLabel("Reason (8–500 characters)").fill("Browser acceptance check");
  await dialog.getByRole("button", { name: "Assign plan", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Quota save temporarily unavailable");
  await page.setViewportSize({ width: 390, height: 360 });
  await dialog.getByRole("button", { name: "Assign plan", exact: true }).scrollIntoViewIfNeeded();
  await expect(dialog.getByRole("button", { name: "Assign plan", exact: true })).toBeInViewport();
  await page.screenshot({ path: info.outputPath("quota-short-viewport.png") });
  await page.keyboard.press("Escape");
  api.override("/accounts/api/admin/quotas/", (route) => route.fulfill({ status: 503, json: { detail: "Quota directory temporarily unavailable" } }));
  await page.getByRole("textbox", { name: "Search quotas", exact: true }).fill("missing");
  await page.getByRole("textbox", { name: "Search quotas", exact: true }).press("Enter");
  await expect(page.getByText("Quota directory temporarily unavailable", { exact: true })).toBeVisible();
  await expect(page.getByText("Quota test account", { exact: true })).toHaveCount(0);
});

test("An active upload stays reachable after hiding its panel", async ({ page, api }, info) => {
  let finish: () => void = () => {};
  const ready = new Promise<void>((resolve) => { finish = resolve; });
  api.override("/files/api/uploads/", (route) => route.fulfill({ status: 201, json: { upload_id: "ui-upload", state: "uploading", part_size: 8388608, expires_at: "2099-01-01T00:00:00Z" } }));
  api.override("/files/api/uploads/ui-upload/parts/", (route) => route.fulfill({ json: { parts: [] } }));
  api.override("/files/api/uploads/ui-upload/complete/", (route) => route.fulfill({ status: 202, json: { upload_id: "ui-upload", state: "verifying" } }));
  api.override("/files/api/uploads/ui-upload/", async (route) => {
    await ready;
    await route.fulfill({ json: { upload_id: "ui-upload", state: "available", file_id: 999 } });
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/drive");
  try {
    await page.locator('input[aria-label="Upload files to My Drive"]').setInputFiles({ name: "ui-proof.txt", mimeType: "text/plain", buffer: Buffer.alloc(0) });
    const panel = page.getByRole("region", { name: "Upload status", exact: true });
    await expect(panel.getByText("ui-proof.txt", { exact: true })).toBeVisible();
    await expect(panel.getByText("Verifying", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "Hide upload status", exact: true }).click();
    await expect(panel).toHaveCount(0);
    await page.getByRole("button", { name: /^Show upload status:/ }).click();
    await expect(panel.getByText("ui-proof.txt", { exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath("upload-reopened.png") });
    finish();
    await expect(panel.getByLabel("Upload completed", { exact: true })).toBeVisible();
  } finally { finish(); }
});

test("Workspace Drive requests carry the selected workspace", async ({ page, api }) => {
  await page.goto("/drive/workspaces/workspace-a/files");
  await expect(page.getByRole("checkbox", { name: "Select Annual report 2024.txt", exact: true })).toBeVisible();
  const scoped = api.requests.filter((r) => r.path === "/drive/api/items/");
  expect(scoped.length).toBeGreaterThan(0);
  expect(scoped.every((r) => r.workspace === "workspace-a")).toBe(true);
  await page.goto("/drive");
  await expect(page.getByRole("checkbox", { name: "Select Annual report 2024.txt", exact: true })).toBeVisible();
  expect(api.requests.filter((r) => r.path === "/drive/api/items/").at(-1)?.workspace).toBeUndefined();
});

test("Organization role change requires confirmation and keeps errors in it", async ({ page, api }) => {
  api.business = true;
  const path = "/accounts/api/tenants/tenant-test/workspaces/workspace-a/members/";
  api.override(`POST ${path}`, (route) => route.fulfill({ status: 503, json: { detail: "Member change temporarily unavailable" } }));
  await page.goto("/organization/admin");
  await page.getByRole("row").filter({ hasText: "Workspace A" }).getByRole("button", { name: "Access", exact: true }).click();
  await page.getByRole("combobox", { name: "Role for member_test", exact: true }).selectOption("viewer");
  const confirmation = page.getByRole("dialog", { name: "Confirm role change", exact: true });
  await expect(confirmation).toBeVisible();
  expect(api.requests.filter((r) => r.path === path && r.method === "POST")).toHaveLength(0);
  await confirmation.getByRole("button", { name: "Change role", exact: true }).click();
  await expect(confirmation.getByRole("alert")).toContainText("Member change temporarily unavailable");
});

test("Organization ignores an old workspace member response", async ({ page, api }) => {
  api.business = true;
  let finish: () => void = () => {};
  const ready = new Promise<void>((resolve) => { finish = resolve; });
  api.override("GET /accounts/api/tenants/tenant-test/workspaces/workspace-a/members/", async (route) => {
    await ready;
    await route.fulfill({ json: { members: [{ assignmentId: "old", membershipId: "old", userId: 9, username: "stale_member", email: "old@example.invalid", organizationRole: "member", workspaceRole: "viewer", status: "active" }] } });
  });
  await page.goto("/organization/admin");
  try {
    await page.getByRole("row").filter({ hasText: "Workspace A" }).getByRole("button", { name: "Access", exact: true }).click();
    const first = page.getByRole("dialog", { name: "Workspace A members", exact: true });
    await expect(first.getByText("Loading members…", { exact: true })).toBeVisible();
    await first.getByRole("button", { name: "Close dialog", exact: true }).click();
    await page.getByRole("row").filter({ hasText: "Workspace B" }).getByRole("button", { name: "Access", exact: true }).click();
    const second = page.getByRole("dialog", { name: "Workspace B members", exact: true });
    await expect(second.getByRole("combobox", { name: "Role for member_test", exact: true })).toBeVisible();
    const response = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith("workspace-a/members/"));
    finish();
    await response;
    await expect(second.getByRole("combobox", { name: "Role for member_test", exact: true })).toBeVisible();
    await expect(second.getByText("stale_member", { exact: true })).toHaveCount(0);
  } finally { finish(); }
});

test("Admin logs expose a keyboard details action", async ({ page, api }, info) => {
  api.admin = true;
  await page.goto("/admin/activity");
  const details = page.getByRole("button", { name: /^View details for Updated fixture/ });
  await details.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Activity details", exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath("admin-log-details.png"), animations: "disabled" });
});

test("Plan creation reports a failed save inside its modal", async ({ page, api }) => {
  api.admin = true;
  api.override("/accounts/api/admin/quota-plans/create/", (route) => route.fulfill({ status: 503, json: { detail: "Plan save temporarily unavailable" } }));
  await page.goto("/admin/infrastructure/quotas/policies");
  await page.getByRole("button", { name: "Add plan", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Create plan", exact: true });
  await dialog.getByLabel("Code", { exact: true }).fill("ui-fixture");
  await dialog.getByLabel("Name", { exact: true }).fill("UI fixture");
  await dialog.getByLabel("Limit (MiB)", { exact: true }).fill("100");
  await dialog.getByLabel("Reason (8–500 characters)").fill("Browser acceptance check");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Plan save temporarily unavailable");
});

test("Settings section navigation supports Back and refresh", async ({ page, isMobile }) => {
  await page.goto("/account/settings?section=general");
  if (isMobile) await page.getByRole("button", { name: "Open navigation", exact: true }).click();
  await page.getByRole("navigation", { name: "Settings sections" }).getByRole("button", { name: "Privacy", exact: true }).click();
  await expect(page).toHaveURL(/section=privacy/);
  await expect(page.getByRole("heading", { name: "Privacy", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "General Settings", exact: true })).toBeVisible();
  await page.goForward();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Privacy", exact: true })).toBeVisible();
});

test("Pending quota saves cannot close with Escape", async ({ page, api }) => {
  api.admin = true;
  let finish: () => void = () => {};
  const ready = new Promise<void>((resolve) => { finish = resolve; });
  api.override("PATCH /accounts/api/admin/quotas/quota-test/", async (route) => {
    await ready;
    await route.fulfill({ status: 503, json: { detail: "Pending-save fixture failure" } });
  });
  await page.goto("/admin/infrastructure/quotas/users");
  await page.getByRole("button", { name: "Manage", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Assign storage plan", exact: true });
  try {
    await dialog.getByLabel("Reason (8–500 characters)").fill("Browser acceptance check");
    await dialog.getByRole("button", { name: "Assign plan", exact: true }).click();
    await expect(dialog.getByRole("button", { name: "Close dialog", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    finish();
    await expect(dialog.getByRole("alert")).toContainText("Pending-save fixture failure");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
  } finally { finish(); }
});
