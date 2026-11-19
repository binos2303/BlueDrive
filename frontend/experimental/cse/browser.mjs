import { createServer } from "node:http";
import { cp, mkdtemp, readFile, realpath, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, devices, firefox, webkit } from "playwright";
import { browserTrustHarness } from "./browser-trust-harness.mjs";
import { authorityJournal } from "./authority-journal.mjs";

const source = fileURLToPath(new URL(".", import.meta.url));
const files = new Set(["/browser-fixture.mjs", "/bench-worker.mjs", "/format.mjs", "/envelopes.mjs", "/trust.mjs",
  "/browser-trust.mjs", "/checkpoints.mjs", "/device-unlock.mjs", "/recovery.mjs"]);
const aliases = {
  "@hpke/core": "/deps/@hpke/core/esm/mod.js",
  "@hpke/common": "/deps/@hpke/common/esm/mod.js",
  "@noble/hashes/sha2.js": "/deps/@noble/hashes/sha2.js",
};
const pageHtml = `<!doctype html><meta charset="utf-8"><title>P6.1 fixture</title>
<script type="importmap">${JSON.stringify({ imports: aliases })}</script>
<script type="module" src="/browser-fixture.mjs"></script>`;
const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://127.0.0.1");
    response.setHeader("Cross-Origin-Opener-Policy", "same-origin");
    response.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
    response.setHeader("Cache-Control", "no-store");
    if (request.method !== "GET") { response.writeHead(405).end(); return; }
    if (url.pathname === "/") { response.setHeader("Content-Type", "text/html; charset=utf-8"); response.end(pageHtml); return; }
    const dependency = /^\/deps\/((?:@hpke\/(?:core|common)\/esm\/|@noble\/hashes\/)[0-9a-zA-Z_./-]+\.js)$/.exec(url.pathname);
    const assets = dependency && !dependency[1].includes("..") ? path.join(source, "node_modules", dependency[1])
      : files.has(url.pathname) ? path.join(source, url.pathname.slice(1)) : null;
    if (!assets) { response.writeHead(404).end(); return; }
    const body = await readFile(assets);
    response.setHeader("Content-Type", "text/javascript; charset=utf-8");
    response.end(body);
  } catch {
    response.writeHead(404).end();
  }
});

const targets = { chromium, firefox, webkit, mobile: chromium };
const labels = process.argv.slice(2);
const selected = labels.length ? labels : ["chromium"];
if (!selected.every((name) => Object.hasOwn(targets, name))) throw new Error("Unknown requested engine");
const tmp = await realpath(os.tmpdir());
const profiles = await mkdtemp(path.join(tmp, "bluedrive-p61-"));
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = "http://127.0.0.1:" + server.address().port;

async function ready(context) {
  const page = context.pages()[0] ?? await context.newPage();
  await page.goto(origin);
  await page.waitForFunction(() => Boolean(globalThis.p61 && globalThis.p615), { timeout: 15000 });
  return page;
}

async function run(engine) {
  const type = targets[engine];
  const useChromium = type === chromium;
  const mobile = engine === "mobile";
  const mode = process.env.P61_CHANNEL || (process.platform === "win32" ? "chrome" : "");
  const launch = {
    headless: true,
    ...(useChromium ? { ...(mode ? { channel: mode } : {}), args: ["--enable-precise-memory-info"] } : {}),
    ...(mobile ? devices["Pixel 7"] : {}),
  };
  const profile = path.join(profiles, engine);
  let context;
  let journal;
  let stage = "launch";
  try {
    context = await type.launchPersistentContext(profile, launch);
    const browser = context.browser();
    stage = "device";
    let page = await ready(context);
    const info = await page.evaluate(() => ({ userAgent: navigator.userAgent, secure: isSecureContext }));
    if (!info.secure) throw new Error("Secure context required");
    const device = await page.evaluate(() => globalThis.p61.initDevice());
    stage = "device-encrypted-bundle";
    journal = authorityJournal(path.join(profiles, engine + "-witness.sqlite"));
    const secureTrust = await browserTrustHarness(context, page, journal);
    stage = "opfs-probe";
    const opfs = await page.evaluate(() => globalThis.p61.probeOpfs());
    stage = "bench";
    const sizes = useChromium && !mobile ? [0, 1, 10, 50, 100] : [1];
    const bench = [];
    for (const size of sizes) {
      const measurement = await page.evaluate(({ size, keep, supported }) => globalThis.p61.runCase(size * 1024 * 1024, keep, supported),
        { size, keep: size === sizes.at(-1), supported: opfs.supported });
      bench.push(measurement);
    }
    if (useChromium && !mobile && bench.some((row) => row.spool !== "OPFS")) throw new Error("Chromium OPFS required");
    const interruptedSeal = await page.evaluate(() => globalThis.p61.interrupted());
    const workersMs = await page.evaluate(() => globalThis.p61.workers());
    stage = "reload";
    await page.reload();
    await page.waitForFunction(() => Boolean(globalThis.p61 && globalThis.p615));
    const reload = await page.evaluate(() => globalThis.p61.deviceStatus());
    const trustReload = await secureTrust.reload(page);
    const resumeReload = await page.evaluate(() => globalThis.p61.resumeAfterNavigation(false));
    await context.close();
    context = null;
    let profileCopy = "NOT RUN";
    let encryptedProfileCopy = "NOT RUN";
    if (engine === "chromium" && process.platform === "win32") {
      stage = "same-host-profile-copy";
      const copy = path.join(profiles, engine + "-copy");
      await cp(profile, copy, { recursive: true, errorOnExist: true });
      context = await type.launchPersistentContext(copy, launch);
      page = await ready(context);
      profileCopy = (await page.evaluate(() => globalThis.p61.deviceStatus())).persisted ? "KEY USABLE" : "KEY UNAVAILABLE";
      await secureTrust.attach(context);
      encryptedProfileCopy = await secureTrust.restore(page);
      await context.close();
      context = null;
    }
    stage = "restart";
    context = await type.launchPersistentContext(profile, launch);
    page = await ready(context);
    const restart = await page.evaluate(() => globalThis.p61.deviceStatus());
    const resumeRestart = await page.evaluate(() => globalThis.p61.resumeAfterNavigation(true));
    const freshIntent = resumeRestart ? null : await page.evaluate(() => globalThis.p61.freshAfterMissingSpool());
    if (!reload.persisted || !restart.persisted || resumeRestart !== (bench.at(-1).spool === "OPFS") || resumeReload !== resumeRestart) {
      throw new Error("Persistence or resumable storage mismatch");
    }
    stage = "device-checkpoint-restart-and-conflicting-tabs";
    await secureTrust.attach(context);
    const trustRestart = await secureTrust.restart(context, page);
    await context.close();
    context = null;
    stage = "isolated-profile";
    const isolated = await type.launch({ headless: true, ...(useChromium && mode ? { channel: mode } : {}) });
    try {
      const ephemeral = await isolated.newContext();
      page = await ready(ephemeral);
      const privateEmpty = !(await page.evaluate(() => globalThis.p61.deviceStatus())).persisted;
      if (!privateEmpty) throw new Error("Ephemeral profile saw persistent account");
      await ephemeral.close();
      return { engine, status: "PASS", os: os.platform() + " " + os.release(), version: browser?.version() ?? info.userAgent,
        device, opfs, reload: reload.persisted, restart: restart.persisted, ephemeralProfileIsolated: privateEmpty, profileCopy,
        resumeReload, resumeRestart, interruptedSeal, freshIntent, workersMs, bench, encryptedProfileCopy,
        trustInitial: secureTrust.first, trustReload, trustRestart };
    } finally {
      await isolated.close();
    }
  } catch (error) {
    return { engine, status: "FAIL", stage, errorType: error.name, reason: String(error.message).split("\n")[0].slice(0, 180) };
  } finally {
    journal?.close();
    await context?.close();
  }
}

try {
  for (const engine of selected) {
    const result = await run(engine);
    console.log(JSON.stringify(result));
    if (result.status !== "PASS") process.exitCode = 1;
  }
} finally {
  server.close();
  const resolved = await realpath(profiles);
  if (path.dirname(resolved) !== tmp || !path.basename(resolved).startsWith("bluedrive-p61-")) throw new Error("Refusing profile cleanup outside the fixture");
  await rm(resolved, { recursive: true, force: true, maxRetries: 4 });
}
