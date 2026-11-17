import type { Route } from "@playwright/test";
import { test, expect } from "./mocked-api";

function reply(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, json: body, headers: {
    "access-control-allow-origin": route.request().headers().origin || "http://localhost:3000",
    "access-control-allow-credentials": "true",
  } });
}

test("Platform organization creation retries one identity request and reports unavailable storage", async ({ page, api }, testInfo) => {
  api.admin = true;
  let created = false;
  const keys: string[] = [];
  const organization = { id: "new-organization", name: "Fixture organization", status: "active", workspaces: 0, created_at: "2026-11-17T00:00:00Z", pendingAdministratorInvitation: true };
  api.override("/accounts/api/admin/access/", (route) => reply(route, { allowed: true, username: "ui_test", email: "ui-test@example.invalid", role: "super_admin", can_manage_admins: true }));
  api.override("/accounts/api/admin/organizations/", (route) => {
    if (route.request().method() === "GET") return reply(route, { count: created ? 1 : 0, page: 1, page_size: 20, results: created ? [organization] : [], capabilities: { createOrganization: true, reinviteOrganization: true } });
    keys.push(route.request().headers()["idempotency-key"]);
    const body = route.request().postDataJSON();
    expect(Object.keys(body).sort()).toEqual(["admin", "limit_bytes", "member_limit_bytes", "name", "reason", "slug"]);
    expect(body.limit_bytes).toBe(2 * 1024 ** 3);
    expect(body.member_limit_bytes).toBe(0);
    expect(Object.keys(body.admin).sort()).toEqual(["email", "username"]);
    if (keys.length === 1) return reply(route, { detail: "Temporary service interruption. Retry the same request." }, 503);
    created = true;
    return reply(route, { organization, member: { membershipId: "initial-admin", status: "invited" }, myDrive: { tenantId: organization.id, workspaceId: "admin-drive", ownership: "organization" }, storageReady: false }, 201);
  });
  await page.goto("/admin/organizations");
  await page.getByRole("button", { name: "Create organization", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Create organization", exact: true });
  await page.screenshot({ path: testInfo.outputPath("create-organization.png") });
  await dialog.getByLabel("Organization name").fill(organization.name);
  await dialog.getByLabel("Organization identifier").fill("fixture-organization");
  await dialog.getByLabel("Administrator username").fill("fixture-admin");
  await dialog.getByLabel("Administrator email").fill("fixture-admin@example.invalid");
  await dialog.getByLabel("Organization storage limit (GiB)").fill("2");
  await dialog.getByLabel("Reason", { exact: true }).fill("Provision approved fixture organization");
  await dialog.getByRole("button", { name: "Create organization", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Temporary service interruption");
  await dialog.getByRole("button", { name: "Create organization", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("status")).toContainText("Storage is not ready");
  expect(keys).toHaveLength(2);
  expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/);
  expect(keys[1]).toBe(keys[0]);
  await expect(page.getByRole("button", { name: "Resend invitation", exact: true })).toBeVisible();
});

test("Organization employee invitation handles identity conflict and preserves membership actions", async ({ page, api }, testInfo) => {
  api.business = true;
  const members = [{ membershipId: "employee-a", userId: 2, username: "fixture-member", email: "member@example.invalid", role: "member", status: "active", managed: true, myDriveWorkspaceId: "private-drive-a" }];
  let attempted = 0;
  api.override("/accounts/api/tenants/tenant-test/members/", (route) => {
    if (route.request().method() === "GET") return reply(route, { members, capabilities: { inviteAccounts: true, manageAccounts: true } });
    attempted += 1;
    const body = route.request().postDataJSON();
    expect(Object.keys(body).sort()).toEqual(["email", "limit_bytes", "reason", "username"]);
    if (attempted === 1) return reply(route, { detail: "Identity already exists.", fieldErrors: { username: ["Choose another username."] } }, 409);
    members.push({ membershipId: "employee-b", userId: 3, username: body.username, email: body.email, role: "member", status: "invited", managed: true, myDriveWorkspaceId: "private-drive-b" });
    return reply(route, { member: members[1], myDrive: { tenantId: "tenant-test", workspaceId: "private-drive-b", ownership: "organization" }, storageReady: false }, 201);
  });
  api.override("/accounts/api/tenants/tenant-test/memberships/employee-a/suspend/", (route) => {
    expect(route.request().postDataJSON()).toEqual({});
    members[0].status = "suspended";
    return reply(route, { membership: { id: "employee-a", status: "suspended" } });
  });
  await page.goto("/organization/admin");
  await page.getByRole("button", { name: "Members", exact: true }).click();
  await page.getByRole("button", { name: "Invite employee", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Invite employee", exact: true });
  await page.screenshot({ path: testInfo.outputPath("invite-employee.png") });
  await dialog.getByLabel("Username", { exact: true }).fill("existing-fixture");
  await dialog.getByLabel("Email", { exact: true }).fill("employee@example.invalid");
  await dialog.getByLabel("Reason", { exact: true }).fill("Invite approved fixture employee");
  await dialog.getByRole("button", { name: "Send invitation", exact: true }).click();
  await expect(dialog).toContainText("Choose another username.");
  await dialog.getByLabel("Username", { exact: true }).fill("new-fixture-employee");
  await dialog.getByRole("button", { name: "Send invitation", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("status")).toContainText("Storage is not ready");
  await page.getByRole("button", { name: "Suspend", exact: true }).click();
  await page.getByRole("dialog", { name: "Suspend employee" }).getByRole("button", { name: "Suspend employee", exact: true }).click();
  await expect(page.getByRole("button", { name: "Restore", exact: true })).toBeVisible();
});

test("Owner without account capabilities cannot invite organization employees", async ({ page, api }) => {
  api.business = true;
  await page.goto("/organization/admin");
  await page.getByRole("button", { name: "Members", exact: true }).click();
  await expect(page.getByRole("button", { name: "Invite employee", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Suspend", exact: true })).toHaveCount(0);
});

test("Organization activation consumes fragment privately and requires a subsequent sign in", async ({ page, api }, testInfo) => {
  const credential = { uid: "fixture-account", token: "fixture-invitation" };
  let accepted = false;
  let attempted = 0;
  let credentialInRequestUrl = false;
  page.on("request", (request) => { if (request.url().includes(credential.token)) credentialInRequestUrl = true; });
  api.override("/accounts/api/organization-invite/accept/", (route) => {
    const body = route.request().postDataJSON();
    expect(Object.keys(body).sort()).toEqual(["password1", "password2", "token", "uid"]);
    expect(body.uid === credential.uid && body.token === credential.token).toBe(true);
    attempted += 1;
    if (attempted === 1) return reply(route, { detail: "Choose a stronger password.", fieldErrors: { password1: ["This password is too common."] } }, 400);
    accepted = true;
    return reply(route, { activated: true });
  });
  if (testInfo.project.name === "desktop") await page.addInitScript(() => localStorage.setItem("securedrive:theme-preference:v1", "dark"));
  await page.goto(`/organization-invite#${new URLSearchParams(credential)}`);
  await expect(page).toHaveURL(/\/organization-invite$/);
  await page.screenshot({ path: testInfo.outputPath("activate-organization-account.png") });
  await page.getByLabel("New password", { exact: true }).fill("Fixture-only-activation-83!");
  await page.getByLabel("Confirm password", { exact: true }).fill("Fixture-only-activation-83!");
  await page.getByRole("button", { name: "Activate account", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Choose a stronger password.");
  await expect(page.getByLabel("New password", { exact: true })).toHaveAccessibleDescription("This password is too common.");
  await page.getByLabel("New password", { exact: true }).fill("Fixture-only-activation-84!");
  await page.getByLabel("Confirm password", { exact: true }).fill("Fixture-only-activation-84!");
  await page.getByRole("button", { name: "Activate account", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Your account is activated");
  await expect(page.getByRole("link", { name: "Sign in", exact: true })).toHaveAttribute("href", "/login?next=%2Fdrive");
  expect(accepted).toBe(true);
  expect(credentialInRequestUrl).toBe(false);
  expect(await page.evaluate((value) => Object.values(localStorage).some((entry) => entry.includes(value)), credential.token)).toBe(false);
});

test("Organization My Drive retains its home organization when leaving another workspace", async ({ page, api }) => {
  api.business = true;
  api.override("/accounts/api/me/", (route) => reply(route, {
    profile: { username: "fixture-employee", email: "employee@example.invalid" },
    account: { type: "business", tenant: { id: "tenant-test", name: "Selected organization", role: "member" }, upgradeEligible: false },
    myDrive: { tenantId: "home-organization", workspaceId: "private-employee-drive", ownership: "organization" },
    memberships: [{ id: "home-organization", name: "Home organization", type: "business", role: "member" }],
  }));
  await page.goto("/drive/workspaces/workspace-a");
  const switcher = page.getByRole("region", { name: "Workspace switcher", exact: true });
  await switcher.getByRole("button", { name: "Workspace A", exact: true }).click();
  await switcher.getByRole("button", { name: "My Drive Home organization", exact: true }).click();
  await expect(page).toHaveURL(/\/drive$/);
  await expect(switcher.getByRole("button", { name: "My Drive · Home organization", exact: true })).toBeVisible();
  await expect.poll(() => api.requests.filter((request) => request.path === "/drive/api/items/").at(-1)?.workspace).toBeUndefined();
});
