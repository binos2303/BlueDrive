import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { test, expect } from "@playwright/test";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";

const state = resolve("playwright/.auth/user.json");
const apiURL = process.env.E2E_API_URL || "http://localhost:8000";
const downloadAPI = process.env.E2E_DOWNLOAD_API_URL || apiURL;
for (const url of [apiURL, downloadAPI]) {
  if (!["localhost", "127.0.0.1", "[::1]"].includes(new URL(url).hostname)) throw new Error("Use local test APIs only.");
}
test.use({ storageState: existsSync(state) ? state : undefined });

function fixtureStorage(action: "overwrite" | "verify-deleted", name: string, workspaceId: string, username: string, keys: string[] = []): { keys: string[]; overwriteIsolated: boolean; stagingClean: boolean } {
  const script = `
import os,sys,json,io,hashlib,re
os.environ.pop('DEBUG',None)
os.environ.setdefault('DJANGO_SETTINGS_MODULE','securedrive.settings')
import django
django.setup()
from django.conf import settings
from files.models import File,StorageLocation,UploadSession
from files.storage_adapters import get_storage_adapter
try:
 assert settings.DEBUG and settings.SECUREDRIVE_STORAGE_ACCESS_KEY_ID.startswith('sdapp')
 storage=get_storage_adapter()
 name=os.environ['E2E_FIXTURE_NAME']
 assert re.fullmatch(r'ui-download-[0-9]+-Tài liệu.txt',name)
 def count_versions(key):
  response=storage._client.list_object_versions(Bucket=storage._bucket,Prefix=key)
  assert not response.get('IsTruncated')
  return sum(item['Key']==key for item in response.get('Versions',[])+response.get('DeleteMarkers',[]))
 if os.environ['E2E_FIXTURE_ACTION']=='overwrite':
  file=File.objects.get(file_name=name,workspace_id=os.environ['E2E_FIXTURE_WORKSPACE'],owner__username=os.environ['E2E_FIXTURE_USER'])
  assert file.workspace.name==name.split('-Tài')[0] and not file.workspace.is_default
  location=StorageLocation.objects.get(file_version__file=file,file_version__is_current=True,state='available')
  assert location.provider_version_id and location.provider_version_id!='null'
  upload=UploadSession.objects.get(file=file)
  assert count_versions(upload.object_key)==0
  replacement=b'B'*file.file_size
  written=storage.put_object(location.object_ref,io.BytesIO(replacement),size_bytes=len(replacement),sha256_hex=hashlib.sha256(replacement).hexdigest())
  assert written.version_id!=location.provider_version_id and count_versions(location.object_ref)==2
  print(json.dumps({'keys':[location.object_ref,upload.object_key],'overwriteIsolated':True,'stagingClean':True}))
 else:
  keys=json.loads(os.environ['E2E_FIXTURE_KEYS'])
  assert len(keys)==2 and all(re.fullmatch(r'(primary|staging)/[0-9a-f]{32}',key) for key in keys)
  assert all(count_versions(key)==0 for key in keys)
  print(json.dumps({'keys':[],'overwriteIsolated':True,'stagingClean':True}))
except Exception:
 print('Generated fixture storage check failed; provider output and credentials suppressed.',file=sys.stderr)
 sys.exit(1)
`;
  return JSON.parse(execFileSync(resolve("../.venv/Scripts/python.exe"), ["-u", "-"], {
    cwd: resolve("../backend"), input: script, encoding: "utf8",
    env: { ...process.env, E2E_FIXTURE_ACTION: action, E2E_FIXTURE_NAME: name, E2E_FIXTURE_WORKSPACE: workspaceId, E2E_FIXTURE_USER: username, E2E_FIXTURE_KEYS: JSON.stringify(keys) },
    timeout: 30_000,
  }));
}

test("Live native presigned GET downloads exact Workspace bytes using the application storage identity", async ({ page, context, baseURL }, info) => {
  test.skip(!existsSync(state) || process.env.E2E_PRESIGNED_DOWNLOAD !== "1", "Requires a signed-in local test account and explicit live-download opt-in.");
  test.setTimeout(180_000);
  const stamp = Date.now();
  const name = `ui-download-${stamp}-Tài liệu.txt`;
  const payload = Buffer.alloc(16 * 1024 * 1024, 65);
  let workspaceId: string | null = null;
  let fileId: number | null = null;
  let uploadId: string | null = null;
  let fixtureKeys: string[] = [];
  const me = await page.request.get(`${apiURL}/accounts/api/me/`);
  expect(me.status()).toBe(200);
  const account = await me.json();
  expect(account.is_platform_admin).not.toBe(true);
  const csrf = await page.request.get(`${apiURL}/accounts/api/csrf/`);
  const headers = { "X-CSRFToken": (await csrf.json()).csrfToken as string, Origin: baseURL!, Referer: `${baseURL}/drive` };
  const scoped = () => ({ ...headers, "X-Workspace-ID": workspaceId! });
  let binaryProxyCalls = 0;
  page.on("request", (request) => {
    if (/^\/drive\/files\/\d+\/download\/$/.test(new URL(request.url()).pathname)) binaryProxyCalls++;
  });
  // Dùng API cấu hình riêng khi nghiệm thu, không sửa cấu hình hay session đang dùng của người dùng.
  await page.route(/\/drive\/files\/\d+\/download-url\/$/, async (route) => {
      const response = await route.fetch({ url: `${downloadAPI}${new URL(route.request().url()).pathname}` });
      if (response.ok() && (await response.json()).mode === "presigned") {
        // Chỉ ghi đè fixture riêng sau khi API đã ký, để ép tình huống TOCTOU cùng key/kích thước.
        fixtureKeys = fixtureStorage("overwrite", name, workspaceId!, account.profile.username).keys;
      }
      await route.fulfill({ response });
  });
  try {
    const created = await page.request.post(`${apiURL}/accounts/api/workspaces/`, { headers, data: { name: `ui-download-${stamp}`, description: "Temporary direct-download acceptance fixture", default_member_role: "viewer" } });
    expect(created.status()).toBe(201);
    workspaceId = (await created.json()).workspace.id;
    await page.goto(`/drive/workspaces/${workspaceId}/files`);
    await page.getByRole("button", { name: "New in workspace files", exact: true }).click();
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("menuitem", { name: "Upload files", exact: true }).click();
    const admitted = page.waitForResponse((response) => new URL(response.url()).pathname === "/files/api/uploads/" && response.request().method() === "POST");
    await (await chooser).setFiles({ name, mimeType: "text/plain", buffer: payload });
    const admission = await admitted;
    expect(admission.status()).toBe(201);
    uploadId = (await admission.json()).upload_id;
    await expect(page.getByRole("region", { name: "Upload status", exact: true }).getByLabel("Upload completed", { exact: true })).toBeVisible({ timeout: 120_000 });
    const listing = await page.request.get(`${apiURL}/drive/api/items/?view=drive`, { headers: scoped() });
    const matches = (await listing.json()).items.filter((item: { name: string }) => item.name === name);
    expect(matches).toHaveLength(1);
    expect(matches[0].size).toBe(payload.length);
    fileId = matches[0].id;

    await page.getByRole("checkbox", { name: `Select ${name}`, exact: true }).check();
    const authorization = page.waitForResponse((response) => new URL(response.url()).pathname === `/drive/files/${fileId}/download-url/`);
    const saved = page.waitForEvent("download", { timeout: 30_000 });
    const objectRequest = context.waitForEvent("request", { predicate: (request) => request.method() === "GET" && new URL(request.url()).searchParams.has("X-Amz-Signature"), timeout: 30_000 });
    await page.getByRole("toolbar", { name: "Selected file actions" }).getByRole("button", { name: "Download", exact: true }).click();
    const authorized = await authorization;
    expect(authorized.status()).toBe(200);
    const ticket = await authorized.json();
    expect(ticket.mode).toBe("presigned");
    expect(ticket.filename).toBe(name);
    expect(ticket.expires_in).toBeLessThanOrEqual(300);
    expect(Boolean(new URL(ticket.url).searchParams.get("versionId"))).toBe(true);
    const storageRequest = await objectRequest;
    const sent = await storageRequest.allHeaders();
    expect(sent.cookie).toBeUndefined();
    expect(sent.authorization).toBeUndefined();
    expect(sent["x-workspace-id"]).toBeUndefined();
    expect(sent.referer).toBeUndefined();
    const download = await saved;
    expect(download.suggestedFilename()).toBe(name);
    const receivedBytes = await readFile((await download.path())!);
    expect(receivedBytes.equals(payload)).toBe(true);
    expect(createHash("sha256").update(receivedBytes).digest("hex")).toBe(createHash("sha256").update(payload).digest("hex"));
    expect(binaryProxyCalls).toBe(0);
    expect(download.url() === ticket.url, "Native download must use the original storage URL, never a Blob URL").toBe(true);
    await expect(page.getByText(/^Requested 1 browser download\./)).toBeVisible();
    await expect(page.getByText(/^Completed:/)).toHaveCount(0);
    await expect(page.getByLabel("Download progress", { exact: true })).toHaveCount(0);
    const unsigned = new URL(ticket.url);
    unsigned.search = "";
    const anonymous = await context.browser()!.newContext();
    let expiredUrlDenied = false;
    try {
      const probe = await anonymous.newPage();
      const denied = await probe.goto(unsigned.href);
      expect(denied?.status(), "An anonymous GET must not read the private fixture").toBe(403);
      if (ticket.expires_in <= 10) {
        // Đợi TTL thật trong cấu hình nghiệm thu ngắn; không chờ TTL production trong bộ test thường.
        await new Promise((resolve) => setTimeout(resolve, (ticket.expires_in + 1) * 1000));
        let status: number | undefined;
        try {
          status = (await probe.goto(ticket.url))?.status();
        } catch {
          throw new Error("Expired download probe could not reach the local storage service.");
        }
        expect(status, "Storage must reject an expired signed URL").toBe(403);
        expiredUrlDenied = true;
      }
    } finally {
      await anonymous.close();
    }
    await page.screenshot({ path: info.outputPath("direct-download-completed.png"), animations: "disabled" });
    await info.attach("Direct download evidence", { body: JSON.stringify({ mode: ticket.mode, native: true, versionPinned: true, overwrittenAfterAuthorization: true, expiresIn: ticket.expires_in, bytes: payload.length, exactBytes: true, binaryProxyCalls, cookiesForwarded: false, workspaceHeaderForwarded: false, anonymousReadDenied: true, expiredUrlDenied }), contentType: "application/json" });
  } finally {
    test.setTimeout(240_000);
    if (fileId) {
      const data = { file_ids: [fileId], folder_ids: [] };
      expect((await page.request.post(`${apiURL}/drive/api/items/trash/`, { headers: scoped(), data })).status()).toBe(200);
      expect((await page.request.post(`${apiURL}/drive/api/items/delete/`, { headers: scoped(), data })).status()).toBe(200);
      if (fixtureKeys.length) fixtureStorage("verify-deleted", name, workspaceId!, account.profile.username, fixtureKeys);
    } else if (uploadId) {
      await page.request.post(`${apiURL}/files/api/uploads/${uploadId}/abort/`, { headers: scoped() });
    }
    if (workspaceId) {
      const quota = await page.request.get(`${apiURL}/accounts/api/me/quota/`, { headers: scoped() });
      const usage = await quota.json();
      expect([usage.usedBytes, usage.reservedBytes]).toEqual([0, 0]);
      expect((await page.request.patch(`${apiURL}/accounts/api/workspaces/${workspaceId}/`, { headers, data: { status: "archived" } })).status()).toBe(200);
    }
  }
});
