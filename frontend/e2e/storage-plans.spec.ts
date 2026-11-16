import { test, expect } from "./mocked-api";

test("Storage assignment uses a defined plan and never sends a custom limit", async ({ page, api }, info) => {
  api.admin = true;
  let submitted: unknown;
  api.override("PATCH /accounts/api/admin/quotas/quota-test/", async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ json: { quota: {} } });
  });
  await page.goto("/admin/infrastructure/quotas/users");
  await page.getByRole("button", { name: "Manage", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("option", { name: "Custom quota", exact: true })).toHaveCount(0);
  await expect(dialog.getByLabel("Limit (MiB)", { exact: true })).toHaveCount(0);
  await dialog.getByRole("combobox", { name: "Storage plan", exact: true }).selectOption("free");
  await dialog.getByLabel("Reason (8–500 characters)").fill("Assign a defined storage package");
  await page.screenshot({ path: info.outputPath("plan-assignment.png") });
  await dialog.getByRole("button", { name: "Assign plan", exact: true }).click();
  await expect(page.getByText("Storage plan updated for Quota test account.", { exact: true })).toBeVisible();
  expect(submitted).toEqual({ plan_code: "free", reason: "Assign a defined storage package" });
});

test("Missing active plans blocks assignment and offers plan management", async ({ page, api }, info) => {
  api.admin = true;
  api.override("/accounts/api/admin/quota-plans/", (route) => route.fulfill({ json: { plans: [] } }));
  await page.goto("/admin/infrastructure/quotas/users");
  await page.getByRole("button", { name: "Manage", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("No active plan is available for this storage type.", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("link", { name: "Manage plans", exact: true })).toHaveAttribute("href", "/admin/infrastructure/quotas/policies");
  await dialog.getByLabel("Reason (8–500 characters)").fill("Choose from an active preset");
  await expect(dialog.getByRole("button", { name: "Assign plan", exact: true })).toBeDisabled();
  await page.screenshot({ path: info.outputPath("no-active-plans.png") });
});

test("Plan load errors are distinct from an empty catalog and can recover", async ({ page, api }) => {
  api.admin = true;
  let unavailable = true;
  api.override("/accounts/api/admin/quota-plans/", (route) => unavailable
    ? route.fulfill({ status: 503, json: { detail: "Plan catalog temporarily unavailable" } })
    : route.fulfill({ json: { plans: [{ code: "free", name: "Free", scope: "personal", limit_bytes: 10485760, is_active: true }] } }));
  await page.goto("/admin/infrastructure/quotas/users");
  await page.getByRole("button", { name: "Manage", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("alert")).toContainText("Storage plans could not be loaded");
  await expect(dialog.getByText("No active plan is available for this storage type.", { exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Assign plan", exact: true })).toBeDisabled();
  unavailable = false;
  await dialog.getByRole("button", { name: "Refresh plans", exact: true }).click();
  await dialog.getByRole("combobox", { name: "Storage plan", exact: true }).selectOption("free");
  await dialog.getByLabel("Reason (8–500 characters)").fill("Recovered catalog is available");
  await expect(dialog.getByRole("button", { name: "Assign plan", exact: true })).toBeEnabled();
});

test("Personal workspaces only offer active workspace packages", async ({ page, api }) => {
  api.admin = true;
  api.override("/accounts/api/admin/quotas/", (route) => route.fulfill({ json: { count: 1, page: 1, page_size: 20, results: [{
    scope: "workspace", id: "workspace-test", name: "Personal project", detail: "Workspace owner", tenant_kind: "personal", tenant_status: "active", editable: true,
    quota: { id: "workspace-quota", plan_code: "workspace-starter", limit_bytes: 104857600, used_bytes: 32, reserved_bytes: 0, percentage: 0, status: "normal" },
  }] } }));
  api.override("/accounts/api/admin/quota-plans/", (route) => route.fulfill({ json: { plans: [
    { code: "free", name: "Free", scope: "personal", limit_bytes: 10485760, is_active: true },
    { code: "workspace-starter", name: "Workspace Starter", scope: "workspace", limit_bytes: 104857600, is_active: true },
    { code: "retired-workspace", name: "Retired workspace", scope: "workspace", limit_bytes: 209715200, is_active: false },
  ] } }));
  await page.goto("/admin/infrastructure/quotas/workspaces");
  await expect(page.getByPlaceholder("Search personal workspaces")).toBeVisible();
  await page.getByRole("button", { name: "Manage", exact: true }).click();
  const select = page.getByRole("dialog").getByRole("combobox", { name: "Storage plan", exact: true });
  await expect(select.getByRole("option")).toHaveText(["Select a plan", "Workspace Starter — 100.0 MiB"]);
});

test("Unassigned storage keeps its current usage and requires choosing a plan", async ({ page, api }) => {
  api.admin = true;
  api.override("/accounts/api/admin/quotas/", (route) => route.fulfill({ json: { count: 1, page: 1, page_size: 20, results: [{
    scope: "personal", id: "legacy-account", name: "Legacy storage account", detail: "legacy@example.invalid", tenant_status: "active", editable: true,
    quota: { id: "legacy-quota", plan_code: null, limit_bytes: 83886080, used_bytes: 1048576, reserved_bytes: 0, percentage: 1.3, status: "normal" },
  }] } }));
  await page.goto("/admin/infrastructure/quotas/users");
  await expect(page.getByRole("cell", { name: "Not assigned", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "80.0 MiB", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Manage", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Reason (8–500 characters)").fill("Choose a defined package for storage");
  await expect(dialog.getByRole("button", { name: "Assign plan", exact: true })).toBeDisabled();
  await dialog.getByRole("combobox", { name: "Storage plan", exact: true }).selectOption("free");
  await expect(dialog.getByRole("button", { name: "Assign plan", exact: true })).toBeEnabled();
});

test("Storage management opens the plan catalog and creates a package", async ({ page, api }, info) => {
  api.admin = true;
  const plans: { code: string; name: string; scope: string; limit_bytes: number; is_active: boolean; assignments: number }[] = [];
  api.override("/accounts/api/admin/quota-plans/", (route) => route.fulfill({ json: { plans } }));
  api.override("POST /accounts/api/admin/quota-plans/create/", async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toEqual({ code: "personal-plus", name: "Personal Plus", scope: "personal", limit_bytes: 256 * 1024 * 1024, reason: "Create a reusable storage package" });
    const plan = { ...payload, is_active: true, assignments: 0 };
    plans.push(plan);
    await route.fulfill({ status: 201, json: { plan } });
  });
  await page.goto("/admin/infrastructure/quotas");
  await expect(page.getByRole("heading", { name: "Storage plans", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add plan", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Create plan", exact: true });
  await dialog.getByLabel("Code", { exact: true }).fill("personal-plus");
  await dialog.getByLabel("Name", { exact: true }).fill("Personal Plus");
  await dialog.getByRole("combobox", { name: "Scope", exact: true }).selectOption("personal");
  await dialog.getByLabel("Limit (MiB)", { exact: true }).fill("256");
  await dialog.getByLabel("Reason (8–500 characters)").fill("Create a reusable storage package");
  await page.screenshot({ path: info.outputPath("create-storage-plan.png") });
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("Personal Plus", { exact: true })).toBeVisible();
});
