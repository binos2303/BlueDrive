import { test as base, expect, type Page, type Route } from "@playwright/test";

export const files = [
  { id: 101, name: "Annual report 2024.txt", owner: "You", ownerInitials: "UT", modified: "2024-01-01T09:00:00Z", size: 32, type: "document", canManage: true, starred: false },
  { id: 102, name: "Budget review 2025.txt", owner: "You", ownerInitials: "UT", modified: "2025-12-31T12:00:00Z", size: 64, type: "document", canManage: true, starred: false },
  { id: -501, folderId: 501, name: "Research folder", owner: "You", ownerInitials: "UT", modified: "2026-11-01T12:00:00Z", size: null, type: "folder", canManage: true, starred: false },
];
export const workspaces = ["a", "b"].map((id) => ({
  id: `workspace-${id}`, tenantId: "tenant-test", tenantName: "Test organization", tenantKind: "business", name: `Workspace ${id.toUpperCase()}`,
  slug: `workspace-${id}`, description: "UI test fixture", status: "active", isDefault: false, defaultMemberRole: "viewer",
  currentUserRole: "admin", canManage: true, createdByUserId: 1, createdByUsername: "ui_test", createdByInitials: "UT", isOwnedByMe: true, memberCount: 2,
  createdAt: "2026-01-01T00:00:00Z", updatedAt: "2026-11-01T00:00:00Z",
}));
const quota = { id: "quota-test", limit_bytes: 104857600, used_bytes: 32, reserved_bytes: 0, remaining_bytes: 104857568, percentage: 0, plan_code: "free", status: "normal" };
const plan = { code: "free", name: "Free", scope: "personal", limit_bytes: 104857600, is_active: true, assignments: 1 };

export type MockApi = {
  admin: boolean;
  business: boolean;
  items: typeof files;
  unexpected: string[];
  requests: { path: string; method: string; workspace: string | undefined }[];
  override: (path: string, handler: (route: Route) => Promise<void>) => void;
};

export async function installMockApi(page: Page): Promise<MockApi> {
  const overrides = new Map<string, (route: Route) => Promise<void>>();
  const api: MockApi = { admin: false, business: false, items: structuredClone(files).map((item) => ({ ...item, owner: "Me" })), unexpected: [], requests: [], override: (path, handler) => overrides.set(path, handler) };
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const isApi = /^\/(accounts\/api|drive\/api|files\/api|sharing\/api)\//.test(path) || /^\/drive\/(files|folder)\/\d+\//.test(path);
    if (!isApi) return route.continue();
    const method = request.method();
    api.requests.push({ path, method, workspace: request.headers()["x-workspace-id"] });
    const headers = { "access-control-allow-origin": request.headers().origin || "http://localhost:3000", "access-control-allow-credentials": "true" };
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body, headers });
    if (method === "OPTIONS") return route.fulfill({ status: 204, headers: { ...headers, "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS", "access-control-allow-headers": "content-type,x-csrftoken,x-workspace-id,idempotency-key" } });
    const override = overrides.get(`${method} ${path}`) || overrides.get(path);
    if (override) return override(route);
    if (path === "/accounts/api/me/") return json({
      is_platform_admin: api.admin, profile: { username: "ui_test", email: "ui-test@example.invalid" },
      account: { type: api.business ? "business" : "individual", tenant: api.business ? { id: "tenant-test", name: "Test organization", role: "owner" } : null, upgradeEligible: true },
      memberships: [],
    });
    if (path === "/accounts/api/csrf/") return json({ csrfToken: "fixture-token-for-mocked-requests-only" });
    if (/^\/accounts\/api\/(admin|tenants\/[^/]+)\/storage\/capabilities\/$/.test(path)) return json({ detail: "Storage control center is disabled in this fixture." }, 404);
    if (path === "/accounts/api/me/quota/") return json({ configured: true, limitBytes: 104857600, usedBytes: 32, reservedBytes: 0, remainingBytes: 104857568, percentUsed: 0 });
    if (path === "/accounts/api/workspaces/" && method === "GET") return json({ workspaces });
    if (path === "/drive/api/folder-tree/") return json({ items: [] });
    if (path === "/drive/api/items/") {
      const items = url.searchParams.has("folder") ? [] : api.items.filter((item) => item.name.toLowerCase().includes((url.searchParams.get("q") || "").toLowerCase()));
      return json({ items });
    }
    if (path === "/drive/api/items/star/") return json({ detail: "Star updated.", count: 1 });
    if (/^\/drive\/folder\/\d+\/details\/$/.test(path)) return json({ type: "folder", name: "Research folder", owner: "You", location: "My Drive / Research folder", ancestors: [], folder_count: 0, file_count: 0, access: "Owner", shared_by: null, last_action: "Created" });
    if (/^\/drive\/files\/\d+\/details\/$/.test(path)) return json({ type: "file", name: "Annual report 2024.txt", size: 32, mime_type: "text/plain", owner: "You", access: "Owner", encrypted: true, location: "My Drive" });
    if (/^\/drive\/files\/\d+\/view\/$/.test(path)) return route.fulfill({ contentType: "text/plain", body: "UI fixture preview", headers });
    if (path === "/accounts/api/me/activity/") return json({ events: [
      { id: 1, action: "UPLOAD", actionLabel: "Uploaded early", description: "Early fixture event", createdAt: "2026-11-01T05:00:00Z", metadata: {} },
      { id: 2, action: "UPLOAD", actionLabel: "Uploaded later", description: "Later fixture event", createdAt: "2026-11-07T05:00:00Z", metadata: {} },
    ], hasMore: false });
    if (path === "/accounts/api/me/search-history/") return json({ items: [], hasMore: false });
    if (/^\/accounts\/api\/workspaces\/[^/]+\/members\/$/.test(path)) return json({ workspaceId: path.split("/")[4], workspaceName: "Workspace A", members: [], total: 0, page: 1, pageSize: 20, hasNext: false });
    if (/^\/accounts\/api\/workspaces\/[^/]+\/activity\/$/.test(path)) return json({ events: [] });
    if (path === "/accounts/api/admin/access/") return json({ allowed: true, username: "ui_test", email: "ui-test@example.invalid", can_manage_admins: true });
    if (path === "/accounts/api/admin/settings/") return json({ display_name: "Platform console", revision: 0, can_edit: true, effective: {} });
    if (path === "/accounts/api/admin/quota-plans/") return json({ plans: [plan] });
    if (path === "/accounts/api/admin/quota-policy/") return json({ warning_percent: 80, critical_percent: 95 });
    if (path === "/accounts/api/admin/quotas/") return json({ count: 1, page: 1, page_size: 20, results: [{ scope: "personal", id: "account-test", name: "Quota test account", detail: "ui-test@example.invalid", tenant_status: "active", tenant_kind: "personal", editable: true, quota }] });
    if (path === "/accounts/api/admin/quotas/history/") return json({ count: 0, results: [] });
    if (path === "/accounts/api/admin/quotas/configuration-history/") return json({ plan_change_count: 0, policy_change_count: 0, plan_changes: [], policy_changes: [] });
    if (/^\/accounts\/api\/admin\/(activity|audit)\/$/.test(path)) return json({ count: 1, page: 1, page_size: 20, actions: [], results: [{ id: "event-test", created_at: "2026-11-07T05:00:00Z", action: "UPDATE", action_label: "Updated fixture", user: "ui_test", actor: "ui_test", target: "Test account", reason: "UI fixture event", scope: "personal", resource_name: "Fixture.txt" }] });
    if (path === "/accounts/api/tenants/tenant-test/workspaces/") return json({ workspaces });
    if (path === "/accounts/api/tenants/tenant-test/members/") return json({ members: [{ membershipId: "member-test", userId: 2, username: "member_test", email: "member@example.invalid", role: "member", status: "active" }] });
    if (/^\/accounts\/api\/tenants\/tenant-test\/workspaces\/[^/]+\/members\/$/.test(path)) return json({ members: [{ assignmentId: "assignment-test", membershipId: "member-test", userId: 2, username: "member_test", email: "member@example.invalid", organizationRole: "member", workspaceRole: "editor", status: "active" }] });
    api.unexpected.push(`${method} ${path}`);
    return json({ detail: `No UI fixture defined for ${method} ${path}` }, 501);
  });
  return api;
}

export const test = base.extend<{ api: MockApi }>({
  api: [async ({ page }, use) => {
    const api = await installMockApi(page);
    await use(api);
    expect(api.unexpected, "Every mock API request must have an explicit fixture; no request reaches the real backend").toEqual([]);
  }, { auto: true }],
});
export { expect };
