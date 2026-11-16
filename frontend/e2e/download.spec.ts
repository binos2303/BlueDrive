import { readFile } from "node:fs/promises";
import { test, expect } from "./mocked-api";

const filename = "Báo cáo tháng 11.txt";
const payload = Buffer.from("Verified download fixture — tiếng Việt");
const cors = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-credentials": "true", "access-control-expose-headers": "Content-Disposition" };

async function selectFile(page: import("@playwright/test").Page, workspace = false) {
  await page.goto(workspace ? "/drive/workspaces/workspace-a/files" : "/drive");
  await page.getByRole("checkbox", { name: "Select Annual report 2024.txt", exact: true }).check();
  return page.getByRole("toolbar", { name: "Selected file actions" }).getByRole("button", { name: "Download", exact: true });
}

test("Native download uses Content-Disposition, preserves bytes and never buffers a Blob or forwards application cookies", async ({ page, context, api }, info) => {
  const storage = "http://127.0.0.1:9000/download-fixture";
  await context.addCookies([{ name: "sessionid", value: "application-only-test-cookie", url: "http://localhost:8000" }]);
  await page.addInitScript(() => {
    URL.createObjectURL = () => { throw new Error("Native downloads must not buffer Blobs."); };
  });
  api.override("/drive/files/101/download-url/", async (route) => route.fulfill({ headers: cors, json: { mode: "presigned", url: storage, filename, size_bytes: payload.length, expires_in: 180 } }));
  let storageHeaders: Record<string, string> = {};
  await context.route(storage, async (route) => {
    storageHeaders = await route.request().allHeaders();
    await route.fulfill({ headers: { "content-type": "application/octet-stream", "content-length": String(payload.length), "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(filename)}` }, body: payload });
  });
  const button = await selectFile(page, true);
  const saved = page.waitForEvent("download");
  await button.click();
  const download = await saved;
  expect(download.suggestedFilename()).toBe(filename);
  expect((await readFile((await download.path())!)).equals(payload)).toBe(true);
  expect(storageHeaders.cookie).toBeUndefined();
  expect(storageHeaders["x-workspace-id"]).toBeUndefined();
  expect(storageHeaders.authorization).toBeUndefined();
  expect(storageHeaders.referer).toBeUndefined();
  expect(api.requests.find((request) => request.path.endsWith("/download-url/"))?.workspace).toBe("workspace-a");
  expect(api.requests.some((request) => request.path.endsWith("/download/"))).toBe(false);
  await expect(page.getByText(/^Requested 1 browser download\./)).toBeVisible();
  await expect(page.getByLabel("Download progress", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/^Completed:/)).toHaveCount(0);
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }).includes("download-fixture"))).toBe(false);
  await page.screenshot({ path: info.outputPath("native-download-status.png"), animations: "disabled" });
});

test("Encrypted or disabled direct mode retains authenticated backend download", async ({ page, api }) => {
  api.override("/drive/files/101/download-url/", async (route) => route.fulfill({ headers: cors, json: { mode: "backend" } }));
  let credentials = false;
  api.override("/drive/files/101/download/", async (route) => {
    credentials = route.request().headers()["x-workspace-id"] === "workspace-a";
    await route.fulfill({ headers: { ...cors, "content-type": "application/octet-stream", "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(filename)}` }, body: payload });
  });
  const button = await selectFile(page, true);
  const saved = page.waitForEvent("download");
  await button.click();
  const download = await saved;
  expect(download.suggestedFilename()).toBe(filename);
  expect((await readFile((await download.path())!)).equals(payload)).toBe(true);
  expect(credentials).toBe(true);
});

test("Authorization denial never falls back to the binary endpoint", async ({ page, api }) => {
  api.override("/drive/files/101/download-url/", async (route) => route.fulfill({ status: 404, headers: cors, json: { detail: "File access is no longer available." } }));
  const button = await selectFile(page);
  await button.click();
  await expect(page.getByText("Failed: File access is no longer available.", { exact: true })).toBeVisible();
  expect(api.requests.some((request) => request.path.endsWith("/download/"))).toBe(false);
});

test("Unsafe URL schemes are rejected before a storage request", async ({ page, api }) => {
  api.override("/drive/files/101/download-url/", async (route) => route.fulfill({ headers: cors, json: { mode: "presigned", url: "javascript:alert('unsafe')", filename, expires_in: 180, size_bytes: 0 } }));
  const button = await selectFile(page);
  await button.click();
  await expect(page.getByText("Failed: The download service returned an invalid authorization. Retry later.", { exact: true })).toBeVisible();
  expect(api.requests.some((request) => request.path.endsWith("/download/"))).toBe(false);
});

for (const scenario of ["expired", "network"] as const) {
  test(`Native storage ${scenario} failure stays with the browser and never reports completed or silently proxies through Django`, async ({ page, context, api }) => {
    const storage = "http://127.0.0.1:9000/download-fixture";
    api.override("/drive/files/101/download-url/", async (route) => route.fulfill({ headers: cors, json: { mode: "presigned", url: storage, filename, size_bytes: payload.length, expires_in: 180 } }));
    const attempted = new Promise<void>((resolve) => context.route(storage, async (route) => {
      resolve();
      if (scenario === "network") return route.abort();
      await route.fulfill({ status: 403, contentType: "application/xml", body: "<Error><Code>AccessDenied</Code></Error>" });
    }));
    let downloads = 0;
    page.on("download", () => downloads++);
    const button = await selectFile(page);
    await button.click();
    await attempted;
    await expect(page.getByText(/^Requested 1 browser download\./)).toBeVisible();
    await expect(page.getByText(/^Completed:/)).toHaveCount(0);
    await expect(page.getByLabel("Download progress", { exact: true })).toHaveCount(0);
    expect(downloads).toBe(0);
    expect(api.requests.some((request) => request.path.endsWith("/download/"))).toBe(false);
  });
}

test("Folder ZIP still uses the backend binary transport", async ({ page, api }) => {
  const archive = Buffer.from("ZIP transport fixture");
  api.override("/drive/folder/501/download/", async (route) => route.fulfill({ headers: { ...cors, "content-type": "application/zip" }, body: archive }));
  await page.goto("/drive");
  await page.getByRole("checkbox", { name: "Select Research folder", exact: true }).check();
  const saved = page.waitForEvent("download");
  await page.getByRole("toolbar", { name: "Selected file actions" }).getByRole("button", { name: "Download", exact: true }).click();
  const download = await saved;
  expect(download.suggestedFilename()).toBe("Research folder.zip");
  expect((await readFile((await download.path())!)).equals(archive)).toBe(true);
});

test("Multiple selected files each receive fresh authorization and native downloads", async ({ page, context, api }) => {
  for (const id of [101, 102]) {
    api.override(`/drive/files/${id}/download-url/`, async (route) => route.fulfill({ headers: cors, json: { mode: "presigned", url: `http://127.0.0.1:9000/batch-${id}`, filename: `batch-${id}.txt`, expires_in: 180, size_bytes: payload.length } }));
    await context.route(`http://127.0.0.1:9000/batch-${id}`, async (route) => route.fulfill({ headers: { "content-type": "application/octet-stream", "content-disposition": `attachment; filename="batch-${id}.txt"` }, body: payload }));
  }
  const downloads: import("@playwright/test").Download[] = [];
  page.on("download", (download) => downloads.push(download));
  await selectFile(page, true);
  await page.getByRole("checkbox", { name: "Select Budget review 2025.txt", exact: true }).check();
  await page.getByRole("toolbar", { name: "Selected file actions" }).getByRole("button", { name: "Download", exact: true }).click();
  await expect.poll(() => downloads.length).toBe(2);
  expect(downloads.map((download) => download.suggestedFilename()).sort()).toEqual(["batch-101.txt", "batch-102.txt"]);
  for (const download of downloads) expect((await readFile((await download.path())!)).equals(payload)).toBe(true);
  expect(api.requests.filter((request) => request.path.endsWith("/download-url/")).map((request) => request.workspace)).toEqual(["workspace-a", "workspace-a"]);
  await expect(page.getByText(/^Requested 2 browser downloads\./)).toBeVisible();
  await expect(page.getByText(/^Completed:/)).toHaveCount(0);
});

test("Existing item action menu downloads its target file without requiring toolbar selection", async ({ page, context, api }) => {
  api.override("/drive/files/102/download-url/", async (route) => route.fulfill({ headers: cors, json: { mode: "presigned", url: "http://127.0.0.1:9000/context-file", filename, expires_in: 180, size_bytes: payload.length } }));
  await context.route("http://127.0.0.1:9000/context-file", async (route) => route.fulfill({ headers: { "content-type": "application/octet-stream", "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(filename)}` }, body: payload }));
  await page.goto("/drive");
  await page.getByRole("button", { name: "Actions for Budget review 2025.txt", exact: true }).click();
  const saved = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: "Download", exact: true }).click();
  expect((await saved).suggestedFilename()).toBe(filename);
  expect(api.requests.filter((request) => request.path.endsWith("/download-url/")).map((request) => request.path)).toEqual(["/drive/files/102/download-url/"]);
});

test("Retry after an expired native URL requests a new URL instead of reusing the old ticket", async ({ page, context, api }) => {
  let attempts = 0;
  const seen: string[] = [];
  api.override("/drive/files/101/download-url/", async (route) => {
    attempts++;
    await route.fulfill({ headers: cors, json: { mode: "presigned", url: `http://127.0.0.1:9000/retry-fixture?attempt=${attempts}`, filename, expires_in: 180, size_bytes: payload.length } });
  });
  await context.route("http://127.0.0.1:9000/retry-fixture?*", async (route) => {
    const attempt = new URL(route.request().url()).searchParams.get("attempt")!;
    seen.push(attempt);
    if (attempt === "1") return route.fulfill({ status: 403, contentType: "application/xml", body: "<Error><Code>ExpiredToken</Code></Error>" });
    await route.fulfill({ headers: { "content-type": "application/octet-stream", "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(filename)}` }, body: payload });
  });
  const button = await selectFile(page);
  await button.click();
  await expect.poll(() => seen.length).toBe(1);
  const saved = page.waitForEvent("download");
  await button.click();
  expect((await saved).suggestedFilename()).toBe(filename);
  expect(seen).toEqual(["1", "2"]);
  expect(attempts).toBe(2);
  await expect(page.getByText(/^Completed:/)).toHaveCount(0);
});
