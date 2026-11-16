import type { Page } from "@playwright/test";
import { test, expect } from "./mocked-api";

import { setup } from "./storage-topology-fixture";

async function arrange(page: Page, nodeId: string) {
  await page.getByLabel("Arrange with keyboard").selectOption(nodeId);
  await page.getByRole("button", { name: "Move card right", exact: true }).click();
  await expect(page.getByRole("button", { name: "Save layout", exact: true })).toBeEnabled();
}

test("Position-only layout saves and reloads without changing inventory", async ({ page, api }, info) => {
  const { nodes, state } = setup(api);
  const crashes: string[] = []; page.on("pageerror", (error) => crashes.push(error.message));
  await page.goto("/admin/infrastructure/connections");
  await expect(page.getByRole("region", { name: "Storage topology canvas", exact: true })).toBeVisible();
  await arrange(page, nodes[0].id);
  await expect(page.getByRole("combobox", { name: "Storage", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Save layout", exact: true }).click();
  await expect(page.getByText("Your layout was saved.", { exact: false })).toBeVisible();
  const first = structuredClone(state.layout.positions);
  expect(Object.keys(first).sort()).toEqual(nodes.map((node) => node.id).sort());
  for (const position of Object.values(first)) expect(Object.keys(position).sort()).toEqual(["x", "y"]);
  await page.reload();
  await expect(page.getByText("Saved personal layout revision 1", { exact: true })).toBeVisible();
  expect(state.layout.positions).toEqual(first);
  expect(api.requests.filter((request) => !["GET", "OPTIONS"].includes(request.method)).every((request) => request.method === "PATCH" && request.path.endsWith("/layout/"))).toBe(true);
  expect(crashes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("topology-layout.png"), fullPage: true });
});

test("List view has keyboard inspection scoped disk details and Escape", async ({ page, api, isMobile }, info) => {
  const { nodes } = setup(api, 3, true);
  await page.goto("/organization/storage");
  await page.getByRole("button", { name: "List view", exact: true }).click();
  const inspect = page.getByRole("button", { name: `Inspect ${nodes[0].hostname}`, exact: true });
  await inspect.focus(); await page.keyboard.press("Enter");
  const panel = isMobile ? page.getByRole("dialog") : page.getByRole("complementary", { name: `Node inspector: ${nodes[0].hostname}` });
  await expect(panel.getByText(nodes[0].id, { exact: true })).toBeVisible();
  await panel.getByRole("button", { name: "Disks", exact: true }).click();
  await expect(panel.getByText("recorded-disk-1", { exact: true })).toBeVisible();
  await expect(panel.getByText("Source: inventory · Health: unknown", { exact: true })).toBeVisible();
  if (isMobile) { await page.keyboard.press("Escape"); await expect(panel).toHaveCount(0); await expect(inspect).toBeFocused(); }
  else await panel.getByRole("button", { name: "Close node inspector" }).click();
  if (isMobile) await page.getByRole("button", { name: "Filters", exact: true }).click();
  await page.getByLabel("Find nodes", { exact: true }).fill("storage-001");
  await expect(page.getByRole("list", { name: "Storage node list" }).getByRole("listitem")).toHaveCount(1);
  expect(api.requests.filter((request) => request.path.includes("/storage/")).every((request) => request.path.includes("/tenants/tenant-test/"))).toBe(true);
  await page.screenshot({ path: info.outputPath("topology-list.png"), fullPage: true });
});

test("Layout conflict retains edits until explicit discard", async ({ page, api }, info) => {
  const { nodes, state } = setup(api);
  await page.goto("/admin/infrastructure/connections");
  await arrange(page, nodes[0].id);
  state.conflict = true;
  await page.getByRole("button", { name: "Save layout", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "another window" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save layout", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Reload topology", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Discard changes", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Discard layout changes", exact: true }).click();
  await expect(page.getByRole("button", { name: "Reload topology", exact: true })).toBeEnabled();
  expect(state.layout.revision).toBe(0);
  await page.screenshot({ path: info.outputPath("topology-conflict-recovered.png"), fullPage: true });
});

test("Failed refresh preserves inventory and marks it stale", async ({ page, api }) => {
  const { state } = setup(api);
  await page.goto("/admin/infrastructure/connections");
  await expect(page.getByRole("region", { name: "Storage topology canvas", exact: true })).toBeVisible();
  state.fail = true;
  await page.getByRole("button", { name: "Reload topology", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "stale" })).toBeVisible();
  await page.getByRole("button", { name: "List view", exact: true }).click();
  await expect(page.getByRole("list", { name: "Storage node list" }).getByRole("listitem")).toHaveCount(3);
});

test("Empty inventory does not invent servers or live health", async ({ page, api }) => {
  setup(api, 0);
  await page.goto("/admin/infrastructure/connections");
  await expect(page.getByRole("heading", { name: "No node inventory recorded" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Storage topology canvas", exact: true })).toHaveCount(0);
  await expect(page.getByText("Recorded inventory · Health unknown · Source: not_collected", { exact: true })).toBeVisible();
});

test("Oversized topology has a usable paginated node list", async ({ page, api }) => {
  const { state } = setup(api, 120); state.tooLarge = true;
  await page.goto("/admin/infrastructure/connections");
  const list = page.getByRole("list", { name: "Storage node list" });
  await expect(list.getByRole("listitem")).toHaveCount(50);
  await page.getByRole("button", { name: "Next nodes", exact: true }).click();
  await expect(list.getByText("storage-050", { exact: true })).toBeVisible();
  expect(state.writes).toHaveLength(0);
});

test("One hundred recorded nodes keep a bounded request count and interactive inspector", async ({ page, api }, info) => {
  setup(api, 100);
  await page.goto("/admin/infrastructure/connections");
  await expect(page.locator(".react-flow__node-host").first()).toBeVisible();
  const latency = await page.evaluate(async () => {
    const started = performance.now();
    const button = document.querySelector<HTMLButtonElement>(".react-flow__node-host button")!;
    return new Promise<number>((resolve) => {
      const observer = new MutationObserver(() => {
        if (document.querySelector('aside[aria-label^="Node inspector"]') || document.querySelector("dialog[open]")) { observer.disconnect(); resolve(performance.now() - started); }
      });
      observer.observe(document.body, { childList: true, subtree: true }); button.click();
    });
  });
  expect(latency).toBeLessThan(250);
  expect(api.requests.filter((request) => request.path.includes("/storage/")).length).toBeLessThan(12);
  const canvas = page.getByRole("region", { name: "Storage topology canvas", exact: true });
  await canvas.scrollIntoViewIfNeeded();
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const frames = page.evaluate(() => new Promise<{ mean_frame_ms: number; p95_frame_ms: number; max_frame_ms: number }>((resolve) => {
    const samples: number[] = []; let previous = 0;
    function sample(now: number) {
      if (previous) samples.push(now - previous);
      previous = now;
      if (samples.length < 45) requestAnimationFrame(sample);
      else { const sorted = [...samples].sort((a,b) => a-b); resolve({ mean_frame_ms: samples.reduce((a,b) => a+b,0)/samples.length, p95_frame_ms: sorted[Math.floor(sorted.length*.95)], max_frame_ms: sorted[sorted.length-1] }); }
    }
    requestAnimationFrame(sample);
  }));
  await page.mouse.wheel(0, 180); await page.mouse.wheel(80, 0);
  const timing = await frames;
  expect(timing.p95_frame_ms).toBeLessThan(100);
  await info.attach("100-node-benchmark.json", { body: JSON.stringify({ snapshot_nodes: 100, inspector_ms: latency, ...timing, viewport: page.viewportSize(), note: "Mocked inventory and Chrome mouse-wheel pan on the local machine; not a real host-metrics or physical phone benchmark." }, null, 2), contentType: "application/json" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("topology-100.png"), fullPage: true });
});

test("Mouse or emulated touch dragging changes position without writing until Save", async ({ page, api, isMobile }, info) => {
  const { nodes, state } = setup(api);
  await page.goto("/admin/infrastructure/connections");
  await page.getByLabel("Arrange with keyboard").selectOption(nodes[0].id);
  const header = page.locator(`.react-flow__node[data-id="${nodes[0].id}"] .storage-drag-handle`);
  await header.scrollIntoViewIfNeeded();
  const box = (await header.boundingBox())!;
  const start = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  if (isMobile) {
    const client = await page.context().newCDPSession(page);
    await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [start] });
    for (let step = 1; step <= 8; step++) await client.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: start.x + 5 * step, y: start.y + 2 * step }] });
    await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await client.detach();
  } else {
    await page.mouse.move(start.x, start.y); await page.mouse.down();
    await page.mouse.move(start.x + 40, start.y + 16, { steps: 8 }); await page.mouse.up();
  }
  await expect(page.getByRole("button", { name: "Save layout", exact: true })).toBeEnabled();
  expect(state.writes).toHaveLength(0);
  await page.getByRole("button", { name: "Save layout", exact: true }).click();
  await expect(page.getByText("Your layout was saved.", { exact: false })).toBeVisible();
  expect(state.layout.positions[nodes[0].id].x).toBeGreaterThan(24);
  await page.screenshot({ path: info.outputPath("topology-drag.png"), fullPage: true });
});

test("Dark 320px layout and a viewport equivalent to desktop 200 percent zoom fit", async ({ page, api }, info) => {
  setup(api);
  await page.addInitScript(() => localStorage.setItem("securedrive:theme-preference:v1", "dark"));
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto("/admin/infrastructure/connections");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("region", { name: "Storage topology canvas", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("topology-320-dark.png"), fullPage: true });
  await page.setViewportSize({ width: 720, height: 450 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "List view", exact: true }).click();
  await expect(page.getByRole("list", { name: "Storage node list" }).getByRole("listitem")).toHaveCount(3);
  await page.screenshot({ path: info.outputPath("topology-720-zoom-equivalent.png"), fullPage: true });
});
