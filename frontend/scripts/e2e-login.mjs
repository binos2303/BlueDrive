import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const baseURL = new URL(process.env.E2E_BASE_URL || "http://localhost:3000");
const apiURL = new URL(process.env.E2E_API_URL || "http://localhost:8000");
for (const url of [baseURL, apiURL]) {
  if (!["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)) throw new Error("Use local test origins only.");
}
const directory = fileURLToPath(new URL("../playwright/.auth/", import.meta.url));
await mkdir(directory, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: false });
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(new URL("/login?next=%2Fdrive", baseURL).href);
  console.log("AUTH_WINDOW_READY: Sign in manually with a test account in the new Chrome window. Passwords are not read or logged.");
  const deadline = Date.now() + 10 * 60_000;
  let saved = false;
  while (Date.now() < deadline && !page.isClosed()) {
    try {
      const response = await context.request.get(new URL("/accounts/api/me/", apiURL).href, { timeout: 5000 });
      if (response.ok()) {
        const account = await response.json();
        if (account.profile && account.account) {
          const role = account.is_platform_admin ? "admin" : "user";
          await context.storageState({ path: `${directory}/${role}.json` });
          console.log(`AUTH_SAVED: ${role} test session stored in gitignored playwright/.auth/${role}.json`);
          saved = true;
          break;
        }
      }
    } catch { /* Keep the manual sign-in window available during a transient API outage. */ }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  if (!saved) throw new Error("No authenticated test session was captured. Run test:e2e:auth again when ready.");
} finally {
  await browser.close();
}
