import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { test, expect } from "@playwright/test";

const state = resolve("playwright/.auth/user.json");
if (!existsSync(state)) throw new Error("Sign in with a test account first: npm run test:e2e:auth");
const apiURL = process.env.E2E_API_URL || "http://localhost:8000";
if (!["localhost", "127.0.0.1", "[::1]"].includes(new URL(apiURL).hostname)) throw new Error("Use a local test API only.");
test.use({ storageState: state });

test("Live session, Drive and workspace discovery use authenticated APIs", async ({ page }, info) => {
  const me = await page.request.get(`${apiURL}/accounts/api/me/`);
  expect(me.status()).toBe(200);
  const account = await me.json();
  expect(account.profile).toBeTruthy();
  expect(account.is_platform_admin).not.toBe(true);
  const items = page.waitForResponse((r) => new URL(r.url()).pathname === "/drive/api/items/" && r.request().method() === "GET");
  await page.goto("/drive");
  expect((await items).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "My Drive", exact: true })).toBeVisible();
  await expect(page.getByText("Could not load your Drive", { exact: true })).toHaveCount(0);
  const workspaces = await page.request.get(`${apiURL}/accounts/api/workspaces/`);
  expect(workspaces.status()).toBe(200);
  expect(Array.isArray((await workspaces.json()).workspaces)).toBe(true);
  await page.screenshot({ path: info.outputPath("live-drive.png"), fullPage: true, animations: "disabled" });
});

test("Live settings sections and privacy endpoints load without mutations", async ({ page }, info) => {
  for (const section of ["general", "security", "privacy", "connections"]) {
    const paths = ["/accounts/api/me/", ...(section === "privacy" ? ["/accounts/api/me/activity/", "/accounts/api/me/search-history/"] : []), ...(section === "general" ? ["/accounts/api/me/quota/"] : [])];
    const responses = paths.map((path) => page.waitForResponse((r) => new URL(r.url()).pathname === path && r.request().method() === "GET"));
    const errors: string[] = [];
    const listener = (response: import("@playwright/test").Response) => {
      const path = new URL(response.url()).pathname;
      if (path.startsWith("/accounts/api/") && response.status() >= 400) errors.push(`${response.status()} ${path}`);
    };
    page.on("response", listener);
    await page.goto(`/account/settings?section=${section}`);
    for (const response of await Promise.all(responses)) expect(response.status()).toBe(200);
    await expect(page.getByRole("button", { name: /^Account actions for / })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    if (section === "privacy") {
      await expect(page.getByText("Loading activity…", { exact: true })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Retry activity", exact: true })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Retry search history", exact: true })).toHaveCount(0);
    }
    await page.screenshot({ path: info.outputPath(`live-settings-${section}.png`), fullPage: true, animations: "disabled" });
    page.off("response", listener);
    expect(errors).toEqual([]);
  }
});

test("Live multipart upload and download round trip cleans up its exact generated fixture", async ({ page }, info) => {
  test.setTimeout(240_000);
  const recoveredName = process.env.E2E_RECOVER_UPLOAD;
  const name = recoveredName || `ui-acceptance-${Date.now()}.txt`;
  expect(name).toMatch(/^ui-acceptance-\d+\.txt$/);
  const contents = Buffer.alloc(9 * 1024 * 1024, 65);
  const failures: string[] = [];
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (path.startsWith("/files/api/uploads/") && response.status() >= 400) failures.push(`${response.status()} ${path}`);
  });
  await page.goto("/drive");
  await expect(page.getByRole("heading", { name: "My Drive", exact: true })).toBeVisible();
  // 8 MiB + 1 MiB exercise two parts, storage and the server finalizer.
  if (!recoveredName) {
    await page.locator('input[aria-label="Upload files to My Drive"]').setInputFiles({ name, mimeType: "text/plain", buffer: contents });
    const panel = page.getByRole("region", { name: "Upload status", exact: true });
    await expect(panel.getByText(name, { exact: true })).toBeVisible();
    await expect(async () => {
      expect(failures, "Upload control-plane errors (no tokens or signed URLs)").toEqual([]);
      await expect(panel.getByLabel("Upload failed", { exact: true })).toHaveCount(0);
      await expect(panel.getByLabel("Upload completed", { exact: true })).toBeVisible({ timeout: 1000 });
    }).toPass({ timeout: 180_000, intervals: [1000, 3000, 5000] });
    await page.screenshot({ path: info.outputPath("live-upload-completed.png"), animations: "disabled" });
    await page.getByRole("button", { name: "Hide upload status", exact: true }).click();
    await page.reload();
  }
  const checkbox = page.getByRole("checkbox", { name: `Select ${name}`, exact: true });
  await expect(checkbox).toBeVisible();
  const directory = await page.request.get(`${apiURL}/drive/api/items/?view=drive`);
  expect(directory.status()).toBe(200);
  const entry = (await directory.json()).items.find((item: { name: string; id: number }) => item.name === name);
  expect(entry).toBeTruthy();
  const download = await page.request.get(`${apiURL}/drive/files/${entry.id}/download/`);
  expect(download.status()).toBe(200);
  expect((await download.body()).equals(contents), "Downloaded bytes must match the generated fixture before cleanup").toBe(true);
  await page.screenshot({ path: info.outputPath("live-file-verified.png"), animations: "disabled" });
  await checkbox.check();
  await page.getByRole("toolbar", { name: "Selected file actions" }).getByRole("button", { name: "Move to trash", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Move to trash?", exact: true });
  await dialog.getByRole("button", { name: /Move to trash/i }).click();
  await expect(dialog).toHaveCount(0);
  await expect(checkbox).toHaveCount(0);
  await page.goto("/drive/trash");
  await expect(page.getByRole("checkbox", { name: `Select ${name}`, exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath("live-test-file-in-trash.png"), animations: "disabled" });
  await page.getByRole("checkbox", { name: `Select ${name}`, exact: true }).check();
  await page.getByRole("toolbar", { name: "Selected file actions" }).getByRole("button", { name: "Delete permanently", exact: true }).click();
  await page.getByRole("dialog", { name: "Delete permanently?", exact: true }).getByRole("button", { name: "Delete permanently", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: `Select ${name}`, exact: true })).toHaveCount(0);
});
