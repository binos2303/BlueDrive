import { createHash, randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { test, expect } from "@playwright/test";

const state = resolve("playwright/.auth/user.json");
if (!existsSync(state)) throw new Error("Sign in with an ordinary test account first: npm run test:e2e:auth");
const apiURL = process.env.E2E_API_URL || "http://localhost:8000";
if (!["localhost", "127.0.0.1", "[::1]"].includes(new URL(apiURL).hostname)) throw new Error("Use a local test API only.");
test.use({ storageState: state });

type Quota = { configured: boolean; scope?: string; limitBytes: number | null; usedBytes: number | null; reservedBytes: number | null; remainingBytes: number | null };
type Item = { id: number; name: string; size: number };

test("Live Workspace upload reserves, rejects over quota, aborts and consumes only Workspace storage", async ({ page, baseURL }, info) => {
  test.setTimeout(240_000);
  const stamp = Date.now();
  const workspaceName = `ui-upload-quota-${stamp}`;
  const fileName = `ui-ws-upload-${stamp}.txt`;
  const contents = Buffer.alloc(9 * 1024 * 1024, 65);
  const admissions = new Set<string>();
  const calls: { path: string; method: string; workspace: string | undefined }[] = [];
  const snapshots: { step: string; workspace: Quota; personal: Quota }[] = [];
  let workspaceId: string | null = null;
  let verifiedFileId: number | null = null;
  let canArchive = true;
  const me = await page.request.get(`${apiURL}/accounts/api/me/`);
  expect(me.status()).toBe(200);
  const account = await me.json();
  expect(account.is_platform_admin).not.toBe(true);
  const csrf = await page.request.get(`${apiURL}/accounts/api/csrf/`);
  expect(csrf.status()).toBe(200);
  const headers = { "X-CSRFToken": (await csrf.json()).csrfToken as string, Origin: baseURL!, Referer: `${baseURL}/drive` };
  const scopedHeaders = () => ({ ...headers, "X-Workspace-ID": workspaceId! });
  const quota = async (workspace = false): Promise<Quota> => {
    const response = await page.request.get(`${apiURL}/accounts/api/me/quota/`, { headers: workspace ? { "X-Workspace-ID": workspaceId! } : {} });
    expect(response.status()).toBe(200);
    const result = await response.json();
    return { configured: result.configured, scope: result.scope, limitBytes: result.limitBytes, usedBytes: result.usedBytes, reservedBytes: result.reservedBytes, remainingBytes: result.remainingBytes };
  };
  const personalBefore = await quota();
  const snapshot = async (step: string) => {
    const workspace = await quota(true);
    const personal = await quota();
    expect(personal, "Workspace activity must leave private Drive quota unchanged").toEqual(personalBefore);
    snapshots.push({ step, workspace, personal });
    return workspace;
  };
  const items = async (): Promise<Item[]> => {
    const response = await page.request.get(`${apiURL}/drive/api/items/?view=drive`, { headers: { "X-Workspace-ID": workspaceId! } });
    expect(response.status()).toBe(200);
    return (await response.json()).items;
  };
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/files/api/uploads/") && request.method() !== "OPTIONS") calls.push({ path, method: request.method(), workspace: request.headers()["x-workspace-id"] });
  });
  try {
    const created = await page.request.post(`${apiURL}/accounts/api/workspaces/`, { headers, data: { name: workspaceName, description: "Temporary Workspace upload/quota acceptance fixture", default_member_role: "viewer" } });
    expect(created.status()).toBe(201);
    const workspace = (await created.json()).workspace;
    workspaceId = workspace.id;
    expect(workspace.name).toBe(workspaceName);
    expect(workspace.isDefault).toBe(false);
    expect(workspace.currentUserRole).toBe("admin");
    const before = await snapshot("created");
    expect(before.configured).toBe(true);
    expect(before.scope).toBe("workspace");
    expect([before.usedBytes, before.reservedBytes]).toEqual([0, 0]);
    expect(before.limitBytes).toBeGreaterThan(contents.length);
    expect(before.limitBytes, "Quota admission probe uses the default small test allocation").toBeLessThanOrEqual(100 * 1024 * 1024);

    const reserveBytes = Math.floor(before.limitBytes! / 2) + 1;
    const responses = await Promise.all([0, 1].map((number) => page.request.post(`${apiURL}/files/api/uploads/`, {
      headers: { ...scopedHeaders(), "Idempotency-Key": randomUUID() },
      data: { name: `ui-ws-reservation-${stamp}-${number}.txt`, size_bytes: reserveBytes, sha256: createHash("sha256").update("admission-only: no data will be uploaded").digest("hex"), folder_id: null },
    })));
    for (const response of responses) {
      if (response.status() === 201) admissions.add((await response.json()).upload_id);
    }
    expect(responses.map((response) => response.status()).sort()).toEqual([201, 413]);
    const rejected = responses.find((response) => response.status() === 413)!;
    expect((await rejected.json()).failure_code).toBe("quota_exceeded");
    const reserved = await snapshot("concurrent admission: one reserved, one rejected");
    expect([reserved.usedBytes, reserved.reservedBytes]).toEqual([0, reserveBytes]);
    for (const id of admissions) {
      const aborted = await page.request.post(`${apiURL}/files/api/uploads/${id}/abort/`, { headers: scopedHeaders() });
      expect(aborted.status()).toBe(200);
      expect((await aborted.json()).state).toBe("canceled");
    }
    expect((await snapshot("aborted admission")).reservedBytes).toBe(0);

    await page.goto(`/drive/workspaces/${workspaceId}/files`);
    await expect(page.getByRole("heading", { name: "Workspace files", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: `Account actions for ${account.profile.username}`, exact: true })).toBeVisible();
    await page.getByRole("button", { name: "New in workspace files", exact: true }).click();
    const chooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("menuitem", { name: "Upload files", exact: true }).click();
    const chooser = await chooserPromise;
    const [response] = await Promise.all([
      page.waitForResponse((response) => new URL(response.url()).pathname === "/files/api/uploads/" && response.request().method() === "POST", { timeout: 20_000 }),
      chooser.setFiles({ name: fileName, mimeType: "text/plain", buffer: contents }),
    ]);
    expect(response.status()).toBe(201);
    admissions.add((await response.json()).upload_id);
    const panel = page.getByRole("region", { name: "Upload status", exact: true });
    await expect(panel.getByText(fileName, { exact: true })).toBeVisible();
    await expect(panel.getByLabel("Upload completed", { exact: true })).toBeVisible({ timeout: 180_000 });
    expect(calls.length).toBeGreaterThan(0);
    expect(calls.every((request) => request.workspace === workspaceId), "Every browser upload control-plane request retains its Workspace").toBe(true);
    const completed = await snapshot("completed multipart upload");
    expect([completed.usedBytes, completed.reservedBytes]).toEqual([contents.length, 0]);
    const entry = (await items()).find((item) => item.name === fileName);
    expect(entry?.size).toBe(contents.length);
    const download = await page.request.get(`${apiURL}/drive/files/${entry!.id}/download/`, { headers: { "X-Workspace-ID": workspaceId! } });
    expect(download.status()).toBe(200);
    expect((await download.body()).equals(contents)).toBe(true);
    verifiedFileId = entry!.id;
    const personal = await page.request.get(`${apiURL}/drive/api/items/?view=drive`);
    expect(personal.status()).toBe(200);
    expect((await personal.json()).items.some((item: Item) => item.name === fileName)).toBe(false);
    await page.screenshot({ path: info.outputPath("workspace-upload-completed.png"), animations: "disabled" });
    await info.attach("Workspace upload completed", { path: info.outputPath("workspace-upload-completed.png"), contentType: "image/png" });
  } finally {
    if (workspaceId) {
      for (const id of admissions) {
        const response = await page.request.get(`${apiURL}/files/api/uploads/${id}/`, { headers: { "X-Workspace-ID": workspaceId } });
        if (!response.ok()) { canArchive = false; continue; }
        const upload = await response.json();
        if (["initiated", "uploading"].includes(upload.state)) {
          const aborted = await page.request.post(`${apiURL}/files/api/uploads/${id}/abort/`, { headers: scopedHeaders() });
          if (aborted.status() !== 200) canArchive = false;
        }
        if (["verifying", "scanning"].includes(upload.state)) canArchive = false;
      }
      if (verifiedFileId) {
        const body = { file_ids: [verifiedFileId], folder_ids: [] };
        const trashed = await page.request.post(`${apiURL}/drive/api/items/trash/`, { headers: scopedHeaders(), data: body });
        expect(trashed.status()).toBe(200);
        const deleted = await page.request.post(`${apiURL}/drive/api/items/delete/`, { headers: scopedHeaders(), data: body });
        expect(deleted.status()).toBe(200);
      }
      const after = await snapshot("cleanup");
      if (after.usedBytes !== 0 || after.reservedBytes !== 0) canArchive = false;
      if (canArchive) {
        const archived = await page.request.patch(`${apiURL}/accounts/api/workspaces/${workspaceId}/`, { headers, data: { status: "archived" } });
        expect(archived.status()).toBe(200);
      }
      await info.attach("Workspace quota evidence", { body: JSON.stringify({ workspaceId, workspaceName, archived: canArchive, snapshots, browserUploadRequests: calls }, null, 2), contentType: "application/json" });
      expect(canArchive, "The test fixture must finish without files or reserved quota before archiving").toBe(true);
    }
  }
});
