import { test, expect } from "./mocked-api";

for (const scenario of [
  {
    name: "destination permission loss",
    code: "destination_not_writable",
    message: "Upload stopped because the destination is no longer available for writing.",
    action: "Choose another folder or workspace, or ask its manager to restore write access.",
  },
  {
    name: "security rejection",
    code: "security_scan_rejected",
    message: "The server rejected this upload during verification or security checks.",
    action: "Review the file and select it again after correcting the issue.",
  },
]) {
  test(`Upload failure explains ${scenario.name} and the next step`, async ({ page, api }, info) => {
    api.override("/files/api/uploads/", (route) => route.fulfill({ status: 201, json: {
      upload_id: "publication-fixture", state: "uploading", part_size: 8388608, expires_at: "2099-01-01T00:00:00Z",
    } }));
    api.override("/files/api/uploads/publication-fixture/parts/", (route) => route.fulfill({ json: { parts: [] } }));
    api.override("/files/api/uploads/publication-fixture/complete/", (route) => route.fulfill({ status: 202, json: { state: "verifying" } }));
    api.override("/files/api/uploads/publication-fixture/", (route) => route.fulfill({ json: {
      state: "failed", failure_code: scenario.code,
    } }));
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/drive");
    await expect(page.getByRole("button", { name: "Account actions for ui_test", exact: true })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Select Annual report 2024.txt", exact: true })).toBeVisible();
    await page.locator('input[aria-label="Upload files to My Drive"]').setInputFiles({
      name: "publication-check.txt", mimeType: "text/plain", buffer: Buffer.alloc(0),
    });
    const panel = page.getByRole("region", { name: "Upload status", exact: true });
    await expect(panel.getByRole("alert")).toContainText(scenario.message);
    await expect(panel.getByRole("alert")).toContainText(scenario.action);
    await expect(panel.getByRole("button", { name: "Retry publication-check.txt", exact: true })).toHaveCount(0);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath("upload-failure.png") });
  });
}
