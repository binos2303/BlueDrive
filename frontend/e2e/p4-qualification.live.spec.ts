import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, realpathSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test, expect } from "@playwright/test";

const accountsFile = process.env.P4_FIXTURE_ACCOUNTS;
test.skip(!accountsFile, "P4 live qualification requires its separately approved isolated fixture.");
const privatePath = accountsFile ? realpathSync(accountsFile) : "";
if (accountsFile && !privatePath.replaceAll("\\", "/").endsWith("/.python/p4-final-fixture/app/browser-accounts.json")) {
  throw new Error("P4 accepts only its newly created fixture accounts.");
}
const configuration = accountsFile ? JSON.parse(readFileSync(privatePath, "utf8")) : {};
if (accountsFile && (configuration.backend !== "http://127.0.0.1:18000" || configuration.frontend !== "http://127.0.0.1:13000")) {
  throw new Error("P4 fixture endpoints do not match the approved scope.");
}
const api = configuration.backend as string;
const digest = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");

test("P4 real UI login, multipart, direct download and file lifecycle", async ({ page, context }, info) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(15_000);
  const defaultRole = info.project.name === "mobile" ? "mobile_owner" : "owner";
  const role = process.env.P4_FIXTURE_ACTOR_ROLE || defaultRole;
  if (!["owner", "mobile_owner", "enterprise_a_peer", "enterprise_b_employee"].includes(role)) throw new Error("P4 fixture actor is outside the approved scope.");
  const account = configuration[role];
  const recipient = role.startsWith("enterprise_a") ? configuration.enterprise_a_admin
    : role.startsWith("enterprise_b") ? configuration.enterprise_b_peer : configuration.recipient;
  const expectedPort = role.startsWith("enterprise_a") ? 18643 : role.startsWith("enterprise_b") ? 18653 : 18633;
  const evidenceKey = role === defaultRole ? info.project.name : `${info.project.name}-${role}`;
  const name = `p4-final-${info.project.name}-${Date.now()}.txt`;
  const renamed = name.replace(".txt", "-renamed.txt");
  const folder = name.replace(".txt", "-folder");
  const contents = Buffer.alloc(9 * 1024 * 1024, info.project.name === "mobile" ? 77 : 68);
  writeFileSync(resolve(dirname(privatePath), `browser-intent-${info.project.name}-${Date.now()}.json`), JSON.stringify({
    user_id: account.user_id, name, folder_name: folder, size_bytes: contents.length, sha256: digest(contents),
  }));
  const errors: string[] = [];
  const checks: Promise<void>[] = [];
  let loggedIn = false;
  let uploadedBytes = 0;
  let signedPuts = 0;
  let signedGets = 0;
  let loginCsrf = false;
  let availableObserved = false;
  let uploadId = "";
  let fileId = 0;
  const deniedStorageCapabilityPaths: string[] = [];
  let authorizationUrl = "";
  page.on("pageerror", () => errors.push("client_exception"));
  context.on("requestfailed", (request) => {
    // Không lưu URL/query vì chúng có thể chứa chữ ký ngắn hạn.
    const url = new URL(request.url());
    if (!request.failure()?.errorText.includes("ERR_ABORTED")) errors.push(`network_failure:${url.hostname}:${url.port}`);
  });
  context.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/accounts/api/login/" && request.method() === "POST") {
      loginCsrf = Boolean(request.headers()["x-csrftoken"]);
    }
    if (url.hostname === "s3.localhost") {
      if (Number(url.port) !== expectedPort) errors.push("storage_port_outside_selected_fixture");
      checks.push(request.allHeaders().then((headers) => {
        if (headers.cookie || headers["x-workspace-id"]) errors.push("application_header_sent_to_storage");
        if (request.method() === "PUT") uploadedBytes += Number(headers["content-length"] || 0);
      }));
      if (request.method() === "PUT") {
        signedPuts += 1;
        if (!url.searchParams.has("uploadId") || !url.searchParams.has("X-Amz-Signature")) errors.push("unsigned_part_request");
      }
      if (request.method() === "GET") {
        signedGets += 1;
        if (!url.searchParams.get("versionId")) errors.push("download_version_not_pinned");
      }
    } else if (!["127.0.0.1", "localhost"].includes(url.hostname)) errors.push("external_request");
    if (url.port === "18000" && request.method() === "GET" && url.pathname.endsWith("/download/")) errors.push("binary_download_proxied");
  });
  page.on("response", (response) => {
    const url = new URL(response.url());
    const path = url.pathname;
    // Employee không có storage.view: API cố ý trả 404 và navigation phải ẩn.
    if (role.startsWith("enterprise_") && response.status() === 404
      && /^\/accounts\/api\/tenants\/[^/]+\/storage\/capabilities\/$/.test(path)) {
      deniedStorageCapabilityPaths.push(path);
      return;
    }
    if (response.status() >= 400 && !(path === "/accounts/api/me/" && !loggedIn && response.status() === 403)) {
      errors.push(`http_error:${response.status()}:${path.replace(/\d+/g, "id")}`);
    }
    if (path === "/files/api/uploads/" && response.request().method() === "POST" && response.status() === 201) {
      checks.push(response.json().then((data) => { uploadId = data.upload_id; }));
    }
    if (/^\/drive\/files\/\d+\/download-url\/$/.test(path) && response.status() === 200) {
      checks.push(response.json().then((data) => {
        if (data.mode !== "presigned") errors.push("download_authorization_is_not_direct");
        else authorizationUrl = data.url;
      }));
    }
    if (/^\/files\/api\/uploads\/[^/]+\/$/.test(path) && response.request().method() === "GET" && response.status() === 200) {
      checks.push(response.json().then((data) => {
        if (data.state === "available") availableObserved = true;
      }));
    }
  });

  await page.goto("/login");
  try {
    await page.locator('input[name="email"]').fill(account.email);
    await page.locator('input[name="password"]').fill(account.password);
  } catch { throw new Error("Fixture sign-in input failed; credential values withheld."); }
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "My Drive", exact: true })).toBeVisible();
  loggedIn = true;
  const me = await page.request.get(`${api}/accounts/api/me/`);
  expect(me.status()).toBe(200);
  const snapshot = await me.json();
  expect(snapshot.profile.email === account.email).toBe(true);
  expect(snapshot.myDrive.ownership).toBe(role.startsWith("enterprise_") ? "organization" : "personal");

  if (info.project.name === "mobile") await page.getByRole("button", { name: "Open navigation", exact: true }).click();
  await page.getByRole("button", { name: "New in My Drive", exact: true }).click();
  await page.getByRole("menuitem", { name: "New folder", exact: true }).click();
  const create = page.getByRole("dialog", { name: "New folder", exact: true });
  await create.getByRole("textbox", { name: "Folder name", exact: true }).fill(folder);
  await create.getByRole("button", { name: "Create", exact: true }).click();
  await expect(create).toHaveCount(0);

  await page.locator('input[aria-label="Upload files to My Drive"]').setInputFiles({ name, mimeType: "text/plain", buffer: contents });
  const panel = page.getByRole("region", { name: "Upload status", exact: true });
  await expect(panel.getByText(name, { exact: true })).toBeVisible();
  await Promise.race([
    expect(panel.getByLabel("Upload completed", { exact: true })).toBeVisible({ timeout: 180_000 }),
    panel.getByLabel("Upload failed", { exact: true }).waitFor({ state: "visible", timeout: 180_000 })
      .then(() => { throw new Error("Fixture upload failed; inspect scoped control-plane/provider evidence."); }),
  ]);
  await Promise.all(checks);
  expect(availableObserved, "UI completion must follow server AVAILABLE.").toBe(true);
  expect(uploadId.length > 0).toBe(true);
  const listing = await page.request.get(`${api}/drive/api/items/?view=drive`);
  expect(listing.status()).toBe(200);
  const item = (await listing.json()).items.find((entry: { name: string; id: number }) => entry.name === name);
  fileId = Number(item?.id);
  expect(fileId > 0).toBe(true);
  expect(signedPuts).toBe(2);
  expect(uploadedBytes).toBe(contents.length);
  expect(loginCsrf).toBe(true);
  await page.screenshot({ path: info.outputPath("p4-upload-completed.png"), animations: "disabled" });
  await page.getByRole("button", { name: "Hide upload status", exact: true }).click();
  await page.reload();
  const select = (itemName: string) => page.getByRole("checkbox", { name: `Select ${itemName}`, exact: true });
  const toolbar = () => page.getByRole("toolbar", { name: "Selected file actions" });
  await select(name).check();
  const downloadPromise = page.waitForEvent("download");
  await toolbar().getByRole("button", { name: "Download", exact: true }).click();
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  expect(digest(Buffer.concat(chunks)) === digest(contents)).toBe(true);
  await Promise.all(checks);
  // Download event giữ URL native ngay cả khi Chrome không phát request event cho attachment.
  expect(download.url() === authorizationUrl, "Native download must use the issued URL; values withheld.").toBe(true);
  const nativeUrl = new URL(download.url());
  expect(nativeUrl.hostname === "s3.localhost" && Number(nativeUrl.port) === expectedPort).toBe(true);
  expect(Boolean(nativeUrl.searchParams.get("versionId") && nativeUrl.searchParams.get("X-Amz-Signature"))).toBe(true);

  await toolbar().getByRole("button", { name: "Rename", exact: true }).click();
  const rename = page.getByRole("dialog", { name: /Rename/ });
  await rename.getByRole("textbox").fill(renamed);
  await rename.getByRole("button", { name: /Save|Rename/, exact: true }).click();
  await expect(rename).toHaveCount(0);
  await select(renamed).check();
  await toolbar().getByRole("button", { name: "Move", exact: true }).click();
  const move = page.getByRole("dialog", { name: "Move 1 item", exact: true });
  await move.getByRole("button", { name: folder, exact: true }).click();
  await move.getByRole("button", { name: "Move here", exact: true }).click();
  await expect(move).toHaveCount(0);
  await page.getByRole("button", { name: `Open ${folder}`, exact: true }).click();
  await expect(select(renamed)).toBeVisible();
  const folderPath = new URL(page.url()).pathname;
  await select(renamed).check();
  await toolbar().getByRole("button", { name: "Share", exact: true }).click();
  const share = page.getByRole("dialog", { name: `Manage access — ${renamed}`, exact: true });
  await share.getByLabel("Recipient email", { exact: true }).fill(recipient.email);
  await share.getByRole("button", { name: "Share", exact: true }).click();
  await expect(share.getByRole("combobox", { name: `Permission for ${recipient.username}`, exact: true })).toHaveValue("viewer");
  await share.getByRole("button", { name: "Close", exact: true }).click();
  await expect(share).toHaveCount(0);
  await select(renamed).check();
  await toolbar().getByRole("button", { name: "Move to trash", exact: true }).click();
  const trash = page.getByRole("dialog", { name: "Move to trash?", exact: true });
  await trash.getByRole("button", { name: /Move to trash/i }).click();
  await expect(select(renamed)).toHaveCount(0);
  await page.goto("/drive/trash");
  await select(renamed).check();
  await toolbar().getByRole("button", { name: "Restore selected items", exact: true }).click();
  await expect(select(renamed)).toHaveCount(0);
  await page.goto(folderPath);
  await expect(select(renamed)).toBeVisible();
  await Promise.all(checks);
  if (role.startsWith("enterprise_")) {
    expect(deniedStorageCapabilityPaths.length).toBeGreaterThan(0);
    expect(deniedStorageCapabilityPaths.every((path) => path === `/accounts/api/tenants/${snapshot.myDrive.tenantId}/storage/capabilities/`)).toBe(true);
    await expect(page.getByRole("link", { name: "Organization storage", exact: true })).toHaveCount(0);
  }
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath("p4-restored-file.png"), fullPage: true, animations: "disabled" });
  await context.storageState({ path: resolve(dirname(privatePath), `browser-auth-${evidenceKey}.json`) });
  // Giữ đúng file fixture cho persistence/restore; cleanup cuối dựa trên receipt đã ghi.
  writeFileSync(resolve(dirname(privatePath), `browser-result-${evidenceKey}.json`), JSON.stringify({
    status: "PASS", project: info.project.name, user_id: account.user_id, upload_id: uploadId, file_id: fileId,
    original_name: name, name: renamed, folder_path: folderPath, size_bytes: contents.length,
    sha256: digest(contents), signed_part_puts: signedPuts, signed_gets: signedGets,
    uploaded_bytes: uploadedBytes, csrf_login: loginCsrf, available_before_ui_completion: availableObserved,
    native_download_url_verified: true, expected_storage_port: expectedPort, tenant_id: snapshot.myDrive.tenantId,
    workspace_id: snapshot.myDrive.workspaceId, actor_role: role,
    next_version: JSON.parse(readFileSync(resolve("package.json"), "utf8")).dependencies.next, client_errors: errors.length,
  }, null, 2));
});
