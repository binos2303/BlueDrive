import { test, expect, workspaces } from "./mocked-api";

const emptyFiles = { count: 0, page: 1, page_size: 20, summary: { active: 0, trash: 0, active_metadata_bytes: 0 }, permissions: { can_manage_files: false }, results: [] };

test("Admin access network failures can retry without implying permission denial", async ({ page, api }, info) => {
  api.admin = true;
  let offline = true;
  api.override("/accounts/api/admin/access/", (route) => offline ? route.abort("failed") : route.fulfill({ json: { allowed: true, username: "ui_test", email: "ui-test@example.invalid" } }));
  api.override("/accounts/api/admin/files/", (route) => route.fulfill({ json: emptyFiles }));
  await page.goto("/admin/files");
  await expect(page.getByRole("heading", { name: "Could not verify administrator access", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in as admin", exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("admin-retry.png"), animations: "disabled" });
  offline = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("heading", { name: "File Management", exact: true })).toBeVisible();
});

test("Admin access denial remains denied and does not expose admin pages", async ({ page, api }) => {
  api.override("/accounts/api/admin/access/", (route) => route.fulfill({ status: 403, json: { detail: "Forbidden" } }));
  await page.goto("/admin/files");
  await expect(page.getByRole("heading", { name: "Administrator access required", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in as admin", exact: true })).toBeVisible();
  expect(api.requests.filter((request) => request.path === "/accounts/api/admin/files/")).toHaveLength(0);
});

test("Account connection failure in admin can retry the account request", async ({ page, api }) => {
  let failed = true;
  api.override("GET /accounts/api/me/", (route) => route.fulfill(failed ? { status: 503, json: { detail: "Account service temporarily unavailable" } } : { json: { is_platform_admin: true, profile: { username: "ui_test", email: "ui-test@example.invalid" }, account: { type: "individual", tenant: null, upgradeEligible: false }, memberships: [] } }));
  api.override("/accounts/api/admin/files/", (route) => route.fulfill({ json: emptyFiles }));
  await page.goto("/admin/files");
  await expect(page.getByRole("heading", { name: "Could not load your account", exact: true })).toBeVisible();
  failed = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("heading", { name: "File Management", exact: true })).toBeVisible();
});

test("Repeated active admin scope and identical search complete another request", async ({ page, api }) => {
  api.admin = true;
  api.override("/accounts/api/admin/files/", (route) => route.fulfill({ json: emptyFiles }));
  await page.goto("/admin/files");
  const refresh = page.getByRole("button", { name: "Refresh", exact: true });
  await expect(refresh).toBeEnabled();
  const before = api.requests.filter((request) => request.path === "/accounts/api/admin/files/").length;
  await page.getByRole("button", { name: "All files", exact: true }).click();
  await expect(refresh).toBeEnabled();
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(refresh).toBeEnabled();
  expect(api.requests.filter((request) => request.path === "/accounts/api/admin/files/").length).toBeGreaterThanOrEqual(before + 2);
});

test("Repeated active Users category does not get stuck loading", async ({ page, api }) => {
  api.admin = true;
  api.override("/accounts/api/admin/users/", (route) => route.fulfill({ json: { count: 0, page: 1, page_size: 20, results: [] } }));
  api.override("/accounts/api/admin/overview/", (route) => route.fulfill({ json: { users: { total: 0, platform_admins: 0 } } }));
  await page.goto("/admin/users");
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeEnabled();
  const before = api.requests.filter((request) => request.path === "/accounts/api/admin/users/").length;
  await page.getByRole("group", { name: "Account category", exact: true }).getByRole("button", { name: "Users", exact: true }).click();
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeEnabled();
  expect(api.requests.filter((request) => request.path === "/accounts/api/admin/users/").length).toBeGreaterThan(before);
});

test("Profile saving locks the submitted fields and prevents a second request", async ({ page, api }) => {
  let release = () => {};
  const responseGate = new Promise<void>((resolve) => { release = resolve; });
  api.override("PATCH /accounts/api/me/", async (route) => {
    await responseGate;
    await route.fulfill({ json: { profile: { username: "ui_test", email: "updated@example.invalid" }, account: { type: "individual", tenant: null, upgradeEligible: true }, memberships: [] } });
  });
  await page.goto("/account/settings?section=security");
  const email = page.getByRole("textbox", { name: "Email", exact: true });
  const password = email.locator("xpath=ancestor::form").locator('input[type="password"]');
  await email.fill("updated@example.invalid");
  await password.fill("synthetic-password-never-sent-to-backend");
  const save = page.getByRole("button", { name: "Save changes", exact: true });
  try {
    await save.click();
    await expect(email).toBeDisabled();
    await expect(password).toBeDisabled();
    await expect(page.getByRole("button", { name: "Saving", exact: false }).first()).toBeDisabled();
    await email.locator("xpath=ancestor::form").evaluate((form) => (form as HTMLFormElement).requestSubmit());
    expect(api.requests.filter((request) => request.path === "/accounts/api/me/" && request.method === "PATCH")).toHaveLength(1);
  } finally { release(); }
  await expect(email).toBeEnabled();
  await expect(email).toHaveValue("updated@example.invalid");
  await expect(password).toHaveValue("");
  await expect(page.getByText("Profile saved.", { exact: true })).toBeVisible();
});

test("Clearing Drive search synchronizes the header and survives Back", async ({ page }) => {
  await page.goto("/drive");
  await expect(page.getByRole("button", { name: "Account actions for ui_test", exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Select Annual report 2024.txt", exact: true })).toBeVisible();
  const search = page.getByRole("searchbox", { name: "Search files and folders", exact: true });
  await search.fill("Annual");
  await search.press("Enter");
  await expect(page).toHaveURL(/\/drive\?q=Annual$/);
  await expect(page.getByRole("button", { name: "Clear search", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Clear search", exact: true }).click();
  await expect(page).toHaveURL(/\/drive$/);
  await expect(search).toHaveValue("");
  await expect(page.getByRole("checkbox", { name: "Select Budget review 2025.txt", exact: true })).toBeVisible();
  await page.goBack();
  await expect(search).toHaveValue("Annual");
});

test("List names can open folders with Enter without selecting unrelated rows", async ({ page }) => {
  await page.goto("/drive");
  await page.getByRole("button", { name: "Open Research folder", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/drive\/folders\/501$/);
  await expect(page.getByRole("button", { name: "Back to My Drive", exact: true })).toBeVisible();
});

test("Shared folder retains its sharer, read-only permission and return path", async ({ page, api, isMobile }, info) => {
  api.override("/drive/folder/501/details/", (route) => route.fulfill({ json: { type: "folder", name: "Colleague documents", owner: "colleague", location: "Shared with me", ancestors: [], file_count: 0, folder_count: 0, access: "Viewer", permission: "viewer", shared_by: "colleague" } }));
  await page.goto("/drive/folders/501");
  await expect(page.getByText("Shared by colleague · Viewer access", { exact: true })).toBeVisible();
  if (isMobile) await page.getByRole("button", { name: "Open navigation", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "Drive navigation", exact: true }).getByRole("link", { name: "Shared with me", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("navigation", { name: "Drive navigation", exact: true }).getByRole("link", { name: "My Drive", exact: true })).not.toHaveAttribute("aria-current", "page");
  if (isMobile) {
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "Open navigation", exact: true })).toHaveAttribute("aria-expanded", "false");
  }
  await expect(page.getByRole("button", { name: "Upload files", exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("shared-folder-context.png"), animations: "disabled" });
  await page.getByRole("button", { name: "Back to Shared with me", exact: true }).click();
  await expect(page).toHaveURL(/\/drive\/shared$/);
});

test("Empty personal Drive offers a visible upload picker in the current destination", async ({ page, api }, info) => {
  api.items = [];
  await page.goto("/drive");
  const upload = page.getByRole("button", { name: "Upload files", exact: true });
  await expect(upload).toBeInViewport();
  await page.screenshot({ path: info.outputPath("empty-drive-upload.png"), animations: "disabled" });
  const chooser = page.waitForEvent("filechooser");
  await upload.click();
  expect(await (await chooser).element().getAttribute("aria-label")).toBe("Choose files to upload");
});

test("Drive API failure is announced and Retry restores the list", async ({ page, api }, info) => {
  let failed = true;
  api.override("/drive/api/items/", (route) => route.fulfill(failed ? { status: 503, json: { detail: "Drive temporarily unavailable" } } : { json: { items: api.items } }));
  await page.goto("/drive");
  await expect(page.getByRole("alert", { name: "Could not load your Drive", exact: true })).toContainText("Drive temporarily unavailable");
  await page.screenshot({ path: info.outputPath("drive-load-error.png"), animations: "disabled" });
  failed = false;
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "Select Annual report 2024.txt", exact: true })).toBeVisible();
});

test("Empty Workspace offers upload only to an Editor or administrator", async ({ page, api }) => {
  api.items = [];
  let role = "viewer";
  api.override("/accounts/api/workspaces/", (route) => route.fulfill({ json: { workspaces: workspaces.map((workspace) => ({ ...workspace, currentUserRole: role, canManage: false })) } }));
  await page.goto("/drive/workspaces/workspace-a/files");
  await expect(page.getByText("Viewer access", { exact: true })).toBeAttached();
  await expect(page.getByRole("heading", { name: "No files here", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Upload files", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "New in workspace files", exact: true })).toHaveCount(0);
  role = "editor";
  await page.reload();
  await expect(page.getByRole("button", { name: "Upload files", exact: true })).toBeInViewport();
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Upload files", exact: true }).click();
  expect(await (await chooser).element().getAttribute("aria-label")).toBe("Choose files to upload");
});

test("Workspace archive failure remains inside the confirmation dialog", async ({ page, api }, info) => {
  api.business = true;
  api.override("PATCH /accounts/api/tenants/tenant-test/workspaces/workspace-a/", (route) => route.fulfill({ status: 503, json: { detail: "Workspace archive temporarily unavailable" } }));
  await page.goto("/organization/admin");
  await page.getByRole("row").filter({ hasText: "Workspace A" }).getByRole("button", { name: "Archive", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Archive workspace", exact: true });
  await dialog.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Workspace archive temporarily unavailable");
  await page.screenshot({ path: info.outputPath("workspace-archive-error.png"), animations: "disabled" });
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByText("Workspace archive temporarily unavailable", { exact: true })).toHaveCount(0);
});

test("Admin search placeholders use the readable muted token in both themes", async ({ page, api }) => {
  api.admin = true;
  api.override("/accounts/api/admin/files/", (route) => route.fulfill({ json: emptyFiles }));
  for (const route of ["/admin/files", "/admin/activity"]) {
    await page.goto(route);
    const input = page.locator('input[placeholder]').first();
    await expect(input).toBeVisible();
    for (const theme of ["light", "dark"]) {
      const colors = await input.evaluate((element, theme) => {
        document.documentElement.dataset.theme = theme;
        const muted = document.createElement("span");
        muted.style.color = "var(--muted)";
        document.body.append(muted);
        const result = { actual: getComputedStyle(element, "::placeholder").color, expected: getComputedStyle(muted).color, opacity: getComputedStyle(element, "::placeholder").opacity };
        muted.remove();
        return result;
      }, theme);
      expect(colors.actual).toBe(colors.expected);
      expect(colors.opacity).toBe("1");
    }
  }
});
