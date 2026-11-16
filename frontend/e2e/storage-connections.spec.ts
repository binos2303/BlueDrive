import { createHash } from "node:crypto";
import type { Route } from "@playwright/test";
import { test, expect, type MockApi } from "./mocked-api";

const sample = Buffer.from("scc-browser-fixture-".padEnd(64, "x"));
const checksum = createHash("sha256").update(sample).digest("hex");
function fixture(api: MockApi, organization = false, configure = true, runtime = false) {
  api.admin = !organization;
  api.business = organization;
  const base = organization ? "/accounts/api/tenants/tenant-test/storage/" : "/accounts/api/admin/storage/";
  const cluster = { id: "cluster-a", display_name: "Approved LAB storage", slug: "approved-lab", provider: "s3", state: "draft" };
  const connection = { id: "connection-a", cluster_id: cluster.id, revision: 1, profile_id: "approved-lab", endpoint_url: "https://s3.example.invalid", public_endpoint_url: "https://objects.example.invalid", bucket: "existing-data-bucket", state: "draft", last_error_code: null, verified_at: null as string | null, read_verified_at: null as string | null, verification_scope: runtime ? "read_only" : "lab" };
  const probe = { id: "probe-a", mode: runtime ? "runtime" : "lab", state: "awaiting_browser", expired: false, expires_at: "2099-01-01T00:00:00Z", cleanup_bucket: null, error_code: null, checks: { head_bucket: true, versioning: true, cors: true, server_sha256: true, version_pinned: true } };
  const binding = { connection_id: null as string | null, generation: 0 };
  const state = { registered: false, probed: false, failure: false, registrations: [] as unknown[], identities: [] as string[], writes: [] as string[] };
  const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body, headers: { "access-control-allow-origin": route.request().headers().origin || "http://localhost:3000", "access-control-allow-credentials": "true" } });
  const path = `${base}clusters/${cluster.id}/connections/${connection.id}/`;
  api.override(base + "capabilities/", (route) => reply(route, { permissions: { "storage.view": true, "storage.configure": configure }, routing_enabled: false, lab_probes_enabled: !runtime, runtime_probes_enabled: runtime }));
  api.override(base + "clusters/", (route) => reply(route, { results: state.registered ? [cluster] : [], count: state.registered ? 1 : 0, page: 1, has_more: false }));
  api.override(base + "profiles/", (route) => reply(route, { profiles: [{ id: "approved-lab", label: "Approved LAB profile", endpoint_url: connection.endpoint_url, public_endpoint_url: connection.public_endpoint_url, provider: "s3", lab: !runtime }] }));
  api.override(base + "binding/", (route) => {
    if (route.request().method() === "PATCH") {
      const data = route.request().postDataJSON();
      expect(data.expected_generation).toBe(binding.generation);
      expect(connection.state).toBe("ready");
      binding.connection_id = connection.id; binding.generation++;
      state.writes.push("binding");
    }
    return reply(route, { binding, routing_enabled: false });
  });
  api.override(base + "clusters/connect/", (route) => {
    state.registered = true; state.registrations.push(route.request().postDataJSON());
    state.identities.push(route.request().headers()["idempotency-key"]);
    return reply(route, { cluster, connection }, 201);
  });
  api.override(`${base}clusters/${cluster.id}/connections/`, (route) => reply(route, { results: [connection], count: 1, page: 1, has_more: false }));
  api.override(path + "verify/", (route) => {
    connection.state = "read_verified"; connection.read_verified_at = "2026-11-08T10:00:00Z";
    return reply(route, { connection, checks: { head_bucket: true } });
  });
  api.override(path + "probe/", (route) => {
    if (route.request().method() === "GET") return reply(route, { probes: state.probed ? [probe] : [] });
    const request = route.request().postDataJSON();
    if (runtime) expect(request).toEqual({ mode: "runtime", reason: "Verify approved LAB transfer before routing", confirm_runtime_fixture: true });
    else expect(request.confirm_lab_fixture).toBe(true);
    state.probed = true;
    connection.state = "verifying";
    return reply(route, {
      probe,
      authorization: { url: "https://objects.example.invalid/fixture?mock-signature", expires_in: 180 },
      ...(runtime ? { upload_authorization: {
        url: "https://objects.example.invalid/upload?mock-signature", method: "PUT", headers: { "Content-Type": "application/octet-stream" },
        body_base64: sample.toString("base64"), expires_in: 180,
      } } : {}),
    }, 201);
  });
  api.override(path + "probes/probe-a/", (route) => reply(route, {
    probe, authorization: { url: "https://objects.example.invalid/fixture?mock-signature", expires_in: 180 },
    ...(runtime ? { upload_authorization: {
      url: "https://objects.example.invalid/upload?mock-signature", method: "PUT", headers: { "Content-Type": "application/octet-stream" },
      body_base64: sample.toString("base64"), expires_in: 180,
    } } : {}),
  }));
  api.override(path + "probes/probe-a/complete/", (route) => {
    expect(route.request().postDataJSON()).toEqual(runtime ? { sha256: checksum, put_sha256: checksum, put_etag: "\"verified-etag\"" } : { sha256: checksum });
    connection.state = "ready"; connection.verified_at = "2026-11-08T10:01:00Z"; probe.state = "succeeded";
    state.writes.push("complete");
    return reply(route, { probe, connection });
  });
  return { base, cluster, connection, probe, state };
}

async function register(page: import("@playwright/test").Page, runtime = false) {
  await page.getByRole("button", { name: "Connect existing storage", exact: true }).click();
  await page.getByLabel("Storage name", { exact: true }).fill("Approved LAB storage");
  await page.getByLabel("Storage identifier", { exact: true }).fill("approved-lab");
  await page.getByLabel("Approved connection profile").selectOption("approved-lab");
  await page.getByLabel("Reason for registration").fill("Register approved storage for verification");
  await page.getByRole("button", { name: "Register connection", exact: true }).click();
  await expect(page.getByLabel("Connection revision")).toBeVisible();
  await page.getByLabel("Reason for action").fill("Verify approved LAB transfer before routing");
  await page.getByRole("button", { name: "Check read access", exact: true }).click();
  await expect(page.getByRole("button", { name: runtime ? "Verify runtime transfer" : "Verify LAB transfer", exact: true })).toBeEnabled();
}

test("Approved storage registration verifies browser bytes and keeps routing off", async ({ page, api }, info) => {
  const { state } = fixture(api);
  const crashes: string[] = [];
  page.on("pageerror", (error) => crashes.push(error.message));
  await page.route("https://objects.example.invalid/**", async (route) => {
    expect(route.request().headers().cookie).toBeUndefined();
    expect(route.request().headers()["x-workspace-id"]).toBeUndefined();
    await route.fulfill({ body: sample, contentType: "application/octet-stream", headers: { "access-control-allow-origin": "*" } });
  });
  await page.goto("/admin/infrastructure/connections");
  await register(page);
  await page.getByRole("button", { name: "Verify LAB transfer", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Verify and clean up" })).toBeDisabled();
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "Verify and clean up" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Prepare for new uploads" })).toBeEnabled();
  await page.getByRole("button", { name: "Prepare for new uploads" }).click();
  await expect(dialog).toContainText("Routing is off");
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "Prepare destination", exact: true }).click();
  await expect(page.getByText(/Prepared destination · generation 1/)).toBeVisible();
  expect(state.writes).toEqual(["complete", "binding"]);
  expect(state.identities[0]).toMatch(/^[0-9a-f-]{36}$/);
  expect(Object.keys(state.registrations[0] as object).sort()).toEqual(["display_name", "profile_id", "reason", "slug"]);
  expect(crashes).toEqual([]);
  const navigation = page.getByRole("navigation", { name: "Admin navigation", includeHidden: true });
  await expect(navigation.locator('[aria-current="page"]')).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator("#admin-main").evaluate((element) => { element.scrollTop = 0; });
  await page.screenshot({ path: info.outputPath("storage-verified.png"), fullPage: true });
});

test("Runtime verification uses browser multipart PUT and GET without cookies", async ({ page, api }) => {
  const { state } = fixture(api, false, true, true);
  const methods: string[] = [];
  await page.route("https://objects.example.invalid/**", async (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: {
        "access-control-allow-origin": "*", "access-control-allow-methods": "GET, PUT, OPTIONS",
        "access-control-allow-headers": "Content-Type", "access-control-expose-headers": "ETag",
      } });
      return;
    }
    methods.push(request.method());
    expect(request.headers().cookie).toBeUndefined();
    expect(request.headers().authorization).toBeUndefined();
    if (request.method() === "PUT") {
      expect(request.postDataBuffer()).toEqual(sample);
      await route.fulfill({ status: 200, body: "", headers: { "access-control-allow-origin": "*", "access-control-expose-headers": "ETag", "ETag": "\"verified-etag\"" } });
    } else {
      await route.fulfill({ body: sample, contentType: "application/octet-stream", headers: { "access-control-allow-origin": "*" } });
    }
  });
  await page.goto("/admin/infrastructure/connections");
  await register(page, true);
  await page.getByRole("button", { name: "Verify runtime transfer" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("approved existing data bucket");
  await dialog.getByRole("checkbox").check();
  await expect(dialog.getByRole("button", { name: "Verify and clean up", exact: true })).toBeEnabled();
  await dialog.getByRole("button", { name: "Verify and clean up", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Prepare for new uploads" })).toBeEnabled();
  expect(methods).toEqual(["PUT", "GET"]);
  expect(state.writes).toEqual(["complete"]);
});

test("A failed browser check can resume after reload without claiming verified", async ({ page, api }, info) => {
  const { state } = fixture(api);
  state.failure = true;
  await page.route("https://objects.example.invalid/**", (route) => state.failure ? route.abort("failed") : route.fulfill({ body: sample, contentType: "application/octet-stream", headers: { "access-control-allow-origin": "*" } }));
  await page.goto("/admin/infrastructure/connections");
  await register(page);
  await page.getByRole("button", { name: "Verify LAB transfer", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "Verify and clean up" }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Prepare for new uploads" })).toBeDisabled();
  await page.reload();
  await expect(page.getByRole("button", { name: "Retry browser check" })).toBeVisible();
  state.failure = false;
  await page.getByRole("button", { name: "Retry browser check" }).click();
  await expect(page.getByText("Verified and cleaned", { exact: true })).toBeVisible();
  expect(state.writes).toEqual(["complete"]);
  await page.screenshot({ path: info.outputPath("storage-recovered.png"), fullPage: true });
});

test("Organization storage uses its own scope and respects view-only access", async ({ page, api }, info) => {
  const { state, connection } = fixture(api, true, false);
  state.registered = true; connection.state = "read_verified";
  await page.goto("/organization/storage");
  await expect(page.getByRole("heading", { name: "Organization storage", exact: true })).toBeVisible();
  await expect(page.getByLabel("Connection revision")).toBeVisible();
  await expect(page.getByText("Your access is read only.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Check read access", exact: true })).toHaveCount(0);
  expect(api.requests.filter((item) => item.path.includes("/storage/")).every((item) => item.path.startsWith("/accounts/api/tenants/tenant-test/"))).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("organization-storage.png"), fullPage: true });
});

test("Disabled storage control retains the existing unavailable topology state", async ({ page, api }) => {
  api.admin = true;
  await page.goto("/admin/infrastructure/connections");
  await expect(page.getByRole("heading", { name: "Storage Topology", exact: true })).toBeVisible();
  await expect(page.getByText("Topology telemetry not connected", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Connect existing storage", exact: true })).toHaveCount(0);
});

test("Storage layout supports dark theme and a 320px viewport", async ({ page, api }, info) => {
  const { state, connection } = fixture(api);
  state.registered = true; connection.state = "read_verified";
  await page.addInitScript(() => localStorage.setItem("securedrive:theme-preference:v1", "dark"));
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/admin/infrastructure/connections");
  await expect(page.getByLabel("Connection revision")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("heading", { name: "Storage connections", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("storage-320-dark.png"), fullPage: true });
});
