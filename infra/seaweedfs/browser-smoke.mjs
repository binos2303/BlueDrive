import { createRequire } from "node:module";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));

export function browserTicket(input) {
  const ticket = { ...input };
  const origin = new URL(ticket.origin);
  assert(["http:", "https:"].includes(origin.protocol));
  assert(["localhost", "127.0.0.1"].includes(origin.hostname));
  assert.equal(origin.origin, ticket.origin);
  assert(ticket.mode === undefined || ticket.mode === "runtime");
  if (ticket.mode === "runtime") {
    const upload = ticket.upload_authorization;
    assert.equal(upload.method, "PUT");
    assert.equal(typeof upload.body_base64, "string");
    const payload = Buffer.from(upload.body_base64, "base64");
    assert.equal(payload.length, 64);
    assert.equal(payload.toString("base64"), upload.body_base64);
    ticket.put = upload.url;
    ticket.get = ticket.authorization.url;
    ticket.payload = Array.from(payload);
    ticket.headers = upload.headers;
    const part = new URL(ticket.put);
    assert(part.searchParams.get("uploadId"));
    assert.equal(part.searchParams.get("partNumber"), "1");
    const version = new URL(ticket.get).searchParams.get("versionId");
    assert(version && version !== "null");
    ticket.expected_version = version;
  } else {
    ticket.headers = { "x-amz-checksum-sha256": ticket.checksum };
  }
  assert(ticket.headers && typeof ticket.headers === "object" && !Array.isArray(ticket.headers));
  assert(Object.entries(ticket.headers).every(([name, value]) =>
    typeof value === "string" && !["cookie", "authorization", "host"].includes(name.toLowerCase())));
  for (const value of [ticket.put, ticket.get]) {
    const url = new URL(value);
    assert.equal(url.protocol, "http:");
    assert(!url.username && !url.password && !url.hash);
    assert(["localhost", "127.0.0.1", "s3.localhost"].includes(url.hostname));
  }
  return ticket;
}

async function main() {
  const { chromium } = require("@playwright/test");
  let browser;
  try {
    let input = "";
    for await (const chunk of process.stdin) input += chunk;
    const ticket = browserTicket(JSON.parse(input));
    browser = await chromium.launch({ channel: "chrome", headless: true });
    const context = await browser.newContext();
    // Trang intercept có address space public; mô phỏng quyền local đã được người dùng chấp nhận.
    await context.grantPermissions(["local-network-access"], { origin: ticket.origin });
    const page = await context.newPage();
    const harness = `${ticket.origin}/__seaweedfs_browser_gate__`;
    await page.route(harness, (route) => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>SeaweedFS CORS gate</title>" }));
    await page.goto(harness);
    const result = await page.evaluate(async ({ put, get, payload, headers }) => {
      const bytes = new Uint8Array(payload);
      const upload = await fetch(put, { method: "PUT", credentials: "omit", redirect: "error", headers, body: bytes });
      const download = await fetch(get, { credentials: "omit", redirect: "error" });
      const downloaded = new Uint8Array(await download.arrayBuffer());
      const sha256 = async (value) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", value)),
        (byte) => byte.toString(16).padStart(2, "0")).join("");
      return { upload: upload.status, etag: upload.headers.get("ETag"), checksum: upload.headers.get("x-amz-checksum-sha256"),
        download: download.status, version: download.headers.get("x-amz-version-id"), payload: Array.from(downloaded),
        sha256: await sha256(downloaded), put_sha256: await sha256(bytes) };
    }, ticket);
    assert.equal(result.upload, 200);
    assert(result.etag);
    assert.equal(result.download, 200);
    if (ticket.mode === "runtime") {
      assert.equal(result.payload.length, 64);
      assert.equal(result.version, ticket.expected_version);
      // Chỉ trả digest/receipt; backend tự đối chiếu bytes GET bí mật và part thật trên S3.
      process.stdout.write(JSON.stringify({ sha256: result.sha256, put_sha256: result.put_sha256, put_etag: result.etag }) + "\n");
    } else {
      assert.equal(result.checksum, ticket.checksum);
      assert.deepEqual(result.payload, ticket.payload);
      process.stdout.write("Browser gate passed.\n");
    }
  } catch {
    process.stderr.write("Browser gate failed; request URLs and credentials suppressed.\n");
    process.exitCode = 1;
  } finally {
    await browser?.close();
  }
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) await main();
