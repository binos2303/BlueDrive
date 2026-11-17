import type { Route } from "@playwright/test";
import { test, expect } from "./mocked-api";

function reply(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, json: body, headers: {
    "access-control-allow-origin": route.request().headers().origin || "http://localhost:3000",
    "access-control-allow-credentials": "true",
  } });
}

const removal = { id: "request-fixture", workspaceId: "workspace-a", workspaceName: "Workspace A", assignmentId: "assignment-fixture", membershipId: "membership-fixture", targetUsername: "fixture_member", requestedByUsername: "fixture_manager", reason: "Project assignment has ended", status: "pending", createdAt: "2026-11-17T00:00:00Z" };
const member = { assignmentId: removal.assignmentId, membershipId: removal.membershipId, userId: 2, username: removal.targetUsername, email: "member@example.invalid", organizationRole: "member", workspaceRole: "editor", status: "active", isSelf: false, isProtected: false };

test("Enterprise manager requests removal without revoking access and creates fragment invitation links", async ({ page, api }, info) => {
  api.business = true;
  let requested = false;
  let directDeletes = 0;
  const membersPath = "/accounts/api/workspaces/workspace-a/members/";
  api.override(membersPath, (route) => reply(route, { workspaceId: "workspace-a", workspaceName: "Workspace A", members: [{ ...member, pendingRemovalRequestId: requested ? removal.id : null }], total: 1, page: 1, pageSize: 20, hasNext: false, capabilities: { removeMembers: false, requestMemberRemoval: true } }));
  api.override(`${membersPath}${member.assignmentId}/`, (route) => { if (route.request().method() === "DELETE") directDeletes++; return reply(route, {}, 403); });
  api.override(`${membersPath}${member.assignmentId}/removal-requests/`, (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({ reason: removal.reason });
    requested = true;
    return reply(route, { request: removal }, 201);
  });
  api.override("/accounts/api/workspaces/workspace-a/invites/", (route) => reply(route, { invitationId: "invitation-fixture", email: "colleague@example.invalid", role: "viewer", workspaceId: "workspace-a", workspaceName: "Workspace A", inviteToken: "mock-invitation-sentinel", expiresAt: "2026-11-24T00:00:00Z" }, 201));
  await page.goto("/drive/workspaces/workspace-a/members");
  await expect(page.getByRole("button", { name: `Remove ${member.username}`, exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Request removal", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Request member removal", exact: true });
  await dialog.getByLabel("Reason", { exact: true }).fill(removal.reason);
  await page.screenshot({ path: info.outputPath("removal-request.png") });
  await dialog.getByRole("button", { name: "Request removal", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("status")).toContainText("An organization administrator must approve");
  await expect(page.getByRole("button", { name: "Requested", exact: true })).toBeDisabled();
  await expect(page.getByText(member.username, { exact: true })).toBeVisible();
  expect(directDeletes).toBe(0);
  await page.getByLabel("Email address", { exact: true }).fill("colleague@example.invalid");
  await page.getByRole("button", { name: "Create invitation", exact: true }).click();
  const link = new URL(await page.getByLabel("Invitation link", { exact: true }).inputValue());
  expect(link.search).toBe("");
  expect(new URLSearchParams(link.hash.slice(1)).has("token")).toBe(true);
});

test("Organization admin reviews removal, recovers from a stale approval and can reject", async ({ page, api }, info) => {
  api.business = true;
  let status = "pending";
  const decisions: string[] = [];
  const requestedPages: number[] = [];
  api.override("/accounts/api/tenants/tenant-test/workspace-removal-requests/", (route) => {
    const page = Number(new URL(route.request().url()).searchParams.get("page") || 1);
    requestedPages.push(page);
    return reply(route, { requests: status === "pending" ? [{ ...removal, status }] : [], count: status === "pending" ? 21 : 0, page, pageSize: 20, hasNext: status === "pending" && page === 1 });
  });
  api.override(`/accounts/api/tenants/tenant-test/workspace-removal-requests/${removal.id}/decision/`, (route) => {
    const body = route.request().postDataJSON();
    decisions.push(body.decision);
    expect(Object.keys(body).sort()).toEqual(["decision", "reason"]);
    if (body.decision === "approve") return reply(route, { detail: "Membership changed. Reject this stale request and submit a new request." }, 409);
    status = "rejected";
    return reply(route, { request: { ...removal, status } });
  });
  await page.goto("/organization/admin");
  await page.getByRole("button", { name: "Removal requests", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Page 2 · 21 requests", { exact: true })).toBeVisible();
  await expect(page.getByText(`${removal.targetUsername} · ${removal.workspaceName}`, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  const approval = page.getByRole("dialog", { name: "Approve member removal", exact: true });
  await approval.getByLabel("Decision reason").fill("Reviewed current project assignment");
  await approval.getByRole("button", { name: "Approve removal", exact: true }).click();
  await expect(approval.getByRole("alert")).toContainText("Membership changed");
  await expect(approval.getByLabel("Decision reason")).toHaveValue("Reviewed current project assignment");
  await approval.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  const rejection = page.getByRole("dialog", { name: "Reject removal request", exact: true });
  await rejection.getByLabel("Decision reason").fill("Membership was changed after the request");
  await page.screenshot({ path: info.outputPath("removal-review.png") });
  await rejection.getByRole("button", { name: "Reject request", exact: true }).click();
  await expect(rejection).not.toBeVisible();
  await expect(page.getByRole("status")).toContainText("Workspace access is unchanged");
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
  expect(decisions).toEqual(["approve", "reject"]);
  await expect.poll(() => requestedPages.at(-1)).toBe(1);
});

test("SaaS workspace keeps direct removal while an unknown capability fails closed", async ({ page, api }) => {
  let revoked = false;
  let capabilities: { removeMembers: boolean; requestMemberRemoval: boolean } | undefined = undefined;
  const path = "/accounts/api/workspaces/workspace-a/members/";
  api.override(path, (route) => reply(route, { workspaceId: "workspace-a", workspaceName: "Workspace A", members: revoked ? [] : [member], total: revoked ? 0 : 1, page: 1, pageSize: 20, hasNext: false, capabilities }));
  api.override(`${path}${member.assignmentId}/`, (route) => { expect(route.request().method()).toBe("DELETE"); revoked = true; return route.fulfill({ status: 204 }); });
  await page.goto("/drive/workspaces/workspace-a/members");
  await expect(page.getByRole("button", { name: `Remove ${member.username}`, exact: true })).toBeDisabled();
  capabilities = { removeMembers: true, requestMemberRemoval: false };
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await page.getByRole("button", { name: `Remove ${member.username}`, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Remove workspace member", exact: true });
  await dialog.getByRole("button", { name: "Remove member", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Workspace access revoked");
  expect(revoked).toBe(true);
});

test("Administrator fragment and legacy links scrub selectors before activation and retain input on token failure", async ({ page, api }, info) => {
  const token = "mock-administrator-invitation-sentinel";
  const leakedRequests: string[] = [];
  page.on("request", (request) => { if (request.resourceType() !== "document" && request.url().includes(token)) leakedRequests.push(request.resourceType()); });
  let accept = false;
  api.override("/accounts/api/admin-invite/accept/", (route) => {
    const body = route.request().postDataJSON();
    expect(body.token === token && body.uid === "fixture-user").toBe(true);
    return reply(route, accept ? { activated: true } : { detail: "Invitation is invalid or expired." }, accept ? 200 : 400);
  });
  for (const selector of [`#uid=fixture-user&token=${token}`, `?uid=fixture-user&token=${token}`]) {
    const response = await page.goto(`/admin-invite${selector}`);
    expect(response?.headers()["referrer-policy"]).toBe("no-referrer");
    await expect(page).toHaveURL(/\/admin-invite$/);
    await page.getByLabel("New password", { exact: true }).fill("fixture-password-not-a-real-credential");
    await page.getByLabel("Confirm password", { exact: true }).fill("fixture-password-not-a-real-credential");
    await page.getByRole("button", { name: "Activate administrator account", exact: true }).click();
    await expect(page.getByRole("main").getByRole("alert")).toContainText("invalid or expired");
    await expect(page.getByLabel("New password", { exact: true })).toHaveValue("fixture-password-not-a-real-credential");
  }
  accept = true;
  await page.getByRole("button", { name: "Activate administrator account", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("activated");
  await page.screenshot({ path: info.outputPath("admin-invite-activated.png") });
  expect(leakedRequests).toEqual([]);
  expect(await page.evaluate((sentinel) => Object.values(localStorage).some((value) => value.includes(sentinel)) || Object.values(sessionStorage).some((value) => value.includes(sentinel)), token)).toBe(false);
});

test("Workspace invitation preview uses a body and signin continuation never carries the token", async ({ page, api }) => {
  const token = "mock-workspace-invitation-sentinel";
  let allowPreview = false;
  let joined = false;
  const leakedRequests: string[] = [];
  page.on("request", (request) => { if (request.resourceType() !== "document" && request.url().includes(token)) leakedRequests.push(request.resourceType()); });
  api.override("/accounts/api/workspace-invites/preview/", (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON().token === token).toBe(true);
    expect(new URL(route.request().url()).search).toBe("");
    return reply(route, allowPreview ? { workspaceId: "workspace-a", workspaceName: "Workspace A", workspaceDescription: "Fixture invitation", invitedEmail: "ui-test@example.invalid", role: "viewer", invitedBy: "Fixture manager", expiresAt: "2026-11-24T00:00:00Z" } : { detail: "Sign in to preview this invitation." }, allowPreview ? 200 : 403);
  });
  api.override("/accounts/api/workspace-invites/accept/", (route) => { expect(route.request().postDataJSON().token === token).toBe(true); joined = true; return reply(route, { joined: true, alreadyMember: false, workspace: { id: "workspace-a", tenantId: "tenant-test" } }); });
  const response = await page.goto(`/workspace-invite#token=${token}`);
  expect(response?.headers()["referrer-policy"]).toBe("no-referrer");
  await expect(page).toHaveURL(/\/workspace-invite$/);
  await expect(page.getByRole("link", { name: "Sign in", exact: true })).toHaveAttribute("href", "/login?next=%2Fworkspace-invite");
  allowPreview = true;
  await page.goto(`/workspace-invite?token=${token}`);
  await expect(page).toHaveURL(/\/workspace-invite$/);
  await page.getByRole("button", { name: "Accept invitation", exact: true }).click();
  await expect(page.getByRole("heading", { name: "You joined Workspace A", exact: true })).toBeVisible();
  expect(joined).toBe(true);
  expect(leakedRequests).toEqual([]);
});

test("Workspace switcher accepts a newly issued fragment invitation link", async ({ page, api }) => {
  let accepted = false;
  api.override("/accounts/api/workspace-invites/accept/", (route) => {
    expect(route.request().postDataJSON()).toEqual({ token: "mock-pasted-workspace-invitation" });
    expect(new URL(route.request().url()).search).toBe("");
    accepted = true;
    return reply(route, { joined: true, alreadyMember: false, workspace: { id: "workspace-a", tenantId: "tenant-test" } });
  });
  await page.goto("/drive");
  const switcher = page.getByRole("region", { name: "Workspace switcher", exact: true });
  await switcher.getByRole("button").first().click();
  await switcher.getByRole("button", { name: "Join", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Join a workspace", exact: true });
  await dialog.getByLabel("Invitation link or token").fill("https://fixture.example.invalid/workspace-invite#token=mock-pasted-workspace-invitation");
  await dialog.getByRole("button", { name: "Join workspace", exact: true }).click();
  await expect(page).toHaveURL(/\/drive\/workspaces\/workspace-a\/files$/);
  expect(accepted).toBe(true);
});
