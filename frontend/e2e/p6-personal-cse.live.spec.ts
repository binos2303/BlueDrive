import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, realpathSync, unlinkSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { test, expect, type Page } from "@playwright/test";

const path = process.env.BLUEDRIVE_CSE_E2E_DIRECTORY;
const app = "http://127.0.0.1:13600";
const backend = "http://127.0.0.1:18600";
const storage = "http://s3.localhost:18339";
test.use({ screenshot: "off", trace: "off", video: "off" });
test.skip(!path, "P6 CSE uses a separately provisioned local Django/PostgreSQL/SeaweedFS fixture.");
const fixture = path ? realpathSync(path) : "";
if (fixture && !fixture.replaceAll("\\", "/").endsWith("/.python/p6-e2e-fixture")) {
  throw new Error("Unrecognized CSE fixture root.");
}

type Packet = { bundle: { keyId: string }; material: string; public: { sign: string; receive: string } };
const hash = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");
const load = (name: string) => JSON.parse(readFileSync(resolve(fixture, name), "utf8"));
const write = (name: string, data: unknown) => writeFileSync(resolve(fixture, name), JSON.stringify(data));

function approve(devices: Packet[], kit?: Packet, revoked: string[] = []) {
  const descriptor = (item: Packet) => ({ key_id: item.bundle.keyId, public: item.public });
  write("browser-public.json", { devices: devices.map(descriptor), revoked, ...(kit ? { recovery: descriptor(kit) } : {}) });
  const python = process.env.BLUEDRIVE_CSE_E2E_PYTHON;
  const coordinator = resolve(fixture, "../p6_fixture_app.py");
  if (!python || !existsSync(coordinator)) throw new Error("The independent fixture operator is unavailable.");
  const result = JSON.parse(execFileSync(python, ["-B", "-X", "utf8", coordinator, "approve"], { encoding: "utf8", timeout: 20_000 }));
  expect(result.status).toBe("PASS");
}

async function login(page: Page, role = "owner") {
  await page.goto(app + "/login");
  const actor = load("browser-accounts.json")[role];
  try {
    await page.locator('input[name="email"]').fill(actor.email);
    await page.locator('input[name="password"]').fill(actor.password);
  } catch { throw new Error("Fixture sign-in inputs are unavailable."); }
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "My Drive", exact: true })).toBeVisible();
}

const controls = (page: Page) => page.getByRole("region", { name: "Personal encryption" });
const modal = (page: Page) => page.getByRole("dialog");
const choose = (page: Page, recovery: boolean) =>
  controls(page).getByRole("button", { name: recovery ? "Verify recovery kit" : "Unlock device", exact: true }).click();

async function generate(page: Page, recovery: boolean): Promise<Packet> {
  await choose(page, recovery);
  const download = page.waitForEvent("download");
  await modal(page).getByRole("button", { name: "Create offline package", exact: true }).click();
  const handle = await download;
  const chunks: Buffer[] = [];
  for await (const chunk of await handle.createReadStream()) chunks.push(Buffer.from(chunk));
  await handle.delete();
  await modal(page).getByRole("button", { name: "Close dialog" }).click();
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

async function usePackage(page: Page, packet: Packet, recovery = false, denied = false) {
  await choose(page, recovery);
  await modal(page).locator('[name="bundle"]').setInputFiles({
    name: "fixture-bundle.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(packet.bundle)),
  });
  try {
    await modal(page).locator('[name="material"]').fill(packet.material);
  } catch { throw new Error("Fixture unlock input is unavailable."); }
  await modal(page).getByRole("button", { name: recovery ? "Verify kit" : "Unlock", exact: true }).click();
  if (denied) {
    await expect(modal(page).getByRole("alert")).toBeVisible();
    await modal(page).getByRole("button", { name: "Close dialog" }).click();
  } else {
    await expect(modal(page)).toHaveCount(0);
    await expect(controls(page).getByRole("status")).toHaveText(recovery ? "Recovery kit verified" : "Encryption unlocked");
  }
}

async function downloadFile(page: Page, name: string, original: Buffer) {
  await page.getByRole("checkbox", { name: `Select ${name}`, exact: true }).check();
  const authorization = page.waitForResponse((response) => /^\/drive\/files\/\d+\/download-url\/$/.test(new URL(response.url()).pathname)
    && response.status() === 200);
  const transfer = page.waitForResponse((response) => new URL(response.url()).origin === storage && response.request().method() === "GET");
  const download = page.waitForEvent("download");
  await page.getByRole("toolbar", { name: "Selected file actions" }).getByRole("button", { name: "Download", exact: true }).click();
  const stored = await transfer;
  expect(stored.status()).toBe(200);
  const url = new URL(stored.url());
  expect(Boolean(url.searchParams.get("versionId") && url.searchParams.get("X-Amz-Signature"))).toBe(true);
  expect(Boolean((await stored.request().allHeaders()).cookie)).toBe(false);
  const finished = await download;
  expect(finished.url().startsWith("blob:")).toBe(true);
  const received = readFileSync(await finished.path() as string);
  expect(received.equals(original) && hash(received) === hash(original)).toBe(true);
  await finished.delete();
  const selected = page.getByRole("checkbox", { name: `Select ${name}`, exact: true });
  if (await selected.isChecked()) await selected.uncheck();
  const fileId = Number(new URL((await authorization).url()).pathname.split("/")[3]);
  return { providerVersion: url.searchParams.get("versionId"), fileId };
}

test("Personal CSE over real multipart, pinned browser download and last-device recovery", async ({ page, browser }) => {
  test.setTimeout(540_000);
  page.setDefaultTimeout(25_000);
  await login(page);
  const file = resolve(fixture, "browser-kit-packages.json");
  const packets = existsSync(file) ? load("browser-kit-packages.json") as { device: Packet; kit: Packet }
    : { device: await generate(page, false), kit: await generate(page, true) };
  write("browser-kit-packages.json", packets);
  if (!load("signed-directory.json").payload.includes(Buffer.from(packets.device.bundle.keyId).toString("hex"))) {
    await usePackage(page, packets.device, false, true);
  }
  approve([packets.device], packets.kit);
  await usePackage(page, packets.device);
  await usePackage(page, packets.kit, true);

  const csrf = (await page.context().cookies(backend)).find((cookie) => cookie.name === "csrftoken");
  if (!csrf) throw new Error("Fixture session did not bootstrap CSRF.");
  const downgraded = await page.request.post(backend + "/files/api/uploads/", {
    headers: { "X-CSRFToken": csrf.value, Origin: app },
    data: { name: "plaintext-denied.txt", size_bytes: 1, sha256: hash(Buffer.from([1])) },
  });
  expect(downgraded.status()).toBe(403);

  const sizes = [0, 1, 2 ** 20, 10 * 2 ** 20, 100 * 2 ** 20];
  const receipts = [];
  const multipart = (url: URL) => url.origin === storage && url.searchParams.has("partNumber");
  let interruptedPart = false;
  for (const size of sizes) {
    const name = `cse-fixture-${size}-${Date.now()}.txt`;
    const original = Buffer.alloc(size, 113);
    const begin = page.waitForResponse((response) => new URL(response.url()).pathname === "/files/api/uploads/"
      && response.request().method() === "POST");
    const input = page.locator('input[aria-label="Upload files to My Drive"]');
    if (size === 10 * 2 ** 20) {
      await page.route(multipart, async (route) => {
        if (!interruptedPart && route.request().method() === "PUT") {
          interruptedPart = true;
          await route.abort("connectionfailed");
        } else await route.continue();
      });
    }
    if (size > 50 * 2 ** 20) {
      // Playwright giới hạn 50 MiB cho dữ liệu truyền trực tiếp vào input.
      const sample = resolve(fixture, name);
      writeFileSync(sample, original, { flag: "wx" });
      try {
        await input.setInputFiles(sample);
        await begin;
      } finally { unlinkSync(sample); }
    } else {
      await input.setInputFiles({ name, mimeType: "text/plain", buffer: original });
    }
    const started = await begin;
    expect(started.status()).toBe(201);
    const sent = started.request().postDataJSON();
    expect(sent.cse.logical_size === size && sent.cse.format === "cse_v1").toBe(true);
    const uploadId = (await started.json()).upload_id;
    const published = page.waitForResponse(async (response) => new URL(response.url()).pathname === `/files/api/uploads/${uploadId}/`
      && response.status() === 200 && response.request().method() === "GET" && (await response.json()).state === "available",
    { timeout: 120_000 });
    await published;
    if (size === 10 * 2 ** 20) {
      expect(interruptedPart).toBe(true);
      await page.unroute(multipart);
    }
    const proof = await downloadFile(page, name, original);
    const wireSize = 152 + size + 16 * Math.ceil(size / (1024 * 1024));
    receipts.push({ name, size, uploadId, ...proof, wireSize, wireDigest: sent.sha256 });
    write("browser-receipts.json", receipts);
  }

  // Đóng session hiện tại và kiểm chứng trình duyệt phải mở khóa lại.
  const logout = await page.request.post(backend + "/accounts/api/logout/", { headers: { "X-CSRFToken": csrf.value, Origin: app } });
  expect([200, 204]).toContain(logout.status());
  await login(page);
  await usePackage(page, packets.device);
  await downloadFile(page, receipts[1].name, Buffer.alloc(1, 113));

  const freshCsrf = (await page.context().cookies(backend)).find((cookie) => cookie.name === "csrftoken");
  if (!freshCsrf) throw new Error("Fixture session did not re-establish CSRF.");
  const cut = await page.request.post(backend + `/file/${receipts[1].fileId}/cut/`, {
    headers: { "X-CSRFToken": freshCsrf.value, Origin: app },
  });
  expect(cut.status()).toBe(409);

  const other = await browser.newContext();
  try {
    const otherPage = await other.newPage();
    await login(otherPage, "other");
    const denied = await otherPage.request.get(backend + `/drive/files/${receipts[1].fileId}/download-url/`);
    expect(denied.status()).toBe(404);
  } finally { await other.close(); }

  const replacement = await browser.newContext({ acceptDownloads: true });
  try {
    const next = await replacement.newPage();
    await login(next);
    const device = await generate(next, false);
    await usePackage(next, device, false, true);
    approve([device], undefined, [packets.device.bundle.keyId]);
    await controls(page).getByRole("button", { name: "Lock", exact: true }).click();
    await usePackage(page, packets.device, false, true);
    await usePackage(next, device);
    await usePackage(next, packets.kit, true);
    await downloadFile(next, receipts[1].name, Buffer.alloc(1, 113));
    await controls(next).getByRole("button", { name: "Lock", exact: true }).click();
    await usePackage(next, device);
    await downloadFile(next, receipts[1].name, Buffer.alloc(1, 113));
  } finally { await replacement.close(); }
});
