import type { Route } from "@playwright/test";
import { test, expect, type MockApi } from "./mocked-api";
import { setup } from "./storage-topology-fixture";

function monitoring(api: MockApi, organization = false) {
  const fixture = setup(api,3,organization);
  const cluster = fixture.nodes[0].cluster_id;
  const observed = new Date().toISOString();
  const health = { status:"healthy", source:"prometheus:approved-fixture", observed_at:observed, last_success_at:observed, stale:false, reason_code:"current_sources_ready" };
  const state = { fail:false, denied:false, configured:true, sse:false, critical:false, ack:false, writes:[] as Record<string,unknown>[], reads:0 };
  const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json:body, headers:{ "access-control-allow-origin":route.request().headers().origin || "http://localhost:3000", "access-control-allow-credentials":"true" } });
  api.override(fixture.base+"capabilities/", (route) => reply(route,{ permissions:{ "storage.view":true, "storage.monitor":true, "storage.configure":false }, topology_enabled:true, monitoring_enabled:true }));
  api.override(`${fixture.base}clusters/${cluster}/telemetry/`, (route) => {
    state.reads++;
    if (state.denied) return reply(route,{detail:"Monitoring access revoked."},403);
    if (state.fail) return reply(route,{detail:"Source unavailable."},503);
    const current = !state.configured ? { ...health, status:"unknown", source:"not_collected", stale:true, observed_at:null } : state.critical ? { ...health, status:"critical" } : health;
    return reply(route,{ cluster_id:cluster, configured:state.configured, revision:state.reads, event_id:`${cluster}:${state.reads}:0`, health:current, expires_at:new Date(Date.parse(observed)+60_000).toISOString(), cluster_metrics:state.configured ? { cluster_read_ready:1, cluster_write_ready:state.critical ? 0 : 1, cluster_failed_disks:0, cluster_offline_nodes:0, usable_capacity_bytes:1024**4, usable_free_bytes:512*1024**3 } : {}, nodes:state.configured ? Object.fromEntries(fixture.nodes.map((node) => [node.id,{ health:state.critical ? { ...health,status:"unknown",reason_code:"node_health_not_confirmed" } : health, metrics:{ node_cpu_percent:15.2, node_ram_percent:35.5, node_uptime_seconds:7200 } }])) : {}, alerts:state.critical ? [{ id:"alert-fixture", cluster_id:cluster, code:"write_quorum_lost", severity:"critical", revision:state.ack ? 2 : 1, first_seen_at:observed, last_seen_at:observed, resolved_at:null, acknowledged_at:state.ack ? observed : null, acknowledged_by:state.ack ? 2 : null }] : [], sse_available:state.sse, poll_seconds:30 });
  });
  api.override(`${fixture.base}clusters/${cluster}/alerts/alert-fixture/acknowledge/`, (route) => {
    state.writes.push(route.request().postDataJSON()); state.ack = true;
    return reply(route,{ unchanged:false });
  });
  api.override(`${fixture.base}clusters/${cluster}/telemetry/stream/`, (route) => {
    state.critical = true;
    return route.fulfill({ status:200, contentType:"text/event-stream", body:`retry: 5000\nid: ${cluster}:2:0\nevent: resync\ndata: {}\n\n`, headers:{ "access-control-allow-origin":route.request().headers().origin || "http://localhost:3000", "access-control-allow-credentials":"true", "cache-control":"no-store" } });
  });
  return { ...fixture, monitoring:state };
}

test("Monitoring refresh keeps arranged positions and stale values after network failure", async ({ page, api }, info) => {
  const { nodes, monitoring:state } = monitoring(api);
  await page.goto("/admin/infrastructure/connections");
  const panel = page.getByLabel("Storage monitoring",{exact:true});
  await expect(panel.getByText("Monitoring: healthy",{exact:true})).toBeVisible();
  await page.getByLabel("Arrange with keyboard").selectOption(nodes[0].id);
  await page.getByRole("button",{name:"Move card right",exact:true}).click();
  const card = page.locator(`[data-id="${nodes[0].id}"]`);
  const position = await card.getAttribute("style");
  state.fail = true;
  await panel.getByRole("button",{name:"Refresh monitoring",exact:true}).click();
  await expect(panel.getByText("Monitoring: unknown · Stale",{exact:true})).toBeVisible();
  await expect(panel.getByText("512 GiB",{exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"Save layout",exact:true})).toBeEnabled();
  expect(await card.getAttribute("style")).toBe(position);
  expect(api.requests.filter((item) => item.path.endsWith("/topology/")).length).toBe(1);
  expect(api.requests.filter((item) => !["GET","OPTIONS"].includes(item.method))).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath("monitoring-stale.png"),fullPage:true});
});

test("Sample expiry becomes unknown without relying on server reconnection", async ({ page, api }) => {
  monitoring(api);
  await page.clock.install();
  await page.goto("/admin/infrastructure/connections");
  const panel = page.getByLabel("Storage monitoring",{exact:true});
  await expect(panel.getByText("Monitoring: healthy",{exact:true})).toBeVisible();
  await page.clock.fastForward(65_000);
  await expect(panel.getByText("Monitoring: unknown · Stale",{exact:true})).toBeVisible();
  await expect(panel.getByText("512 GiB",{exact:true})).toBeVisible();
});

test("Organization inspector shows node metrics and acknowledgement leaves incident active", async ({ page, api, isMobile }, info) => {
  const { nodes, monitoring:state } = monitoring(api,true); state.critical = true;
  await page.goto("/organization/storage");
  const panel = page.getByLabel("Storage monitoring",{exact:true});
  await panel.getByRole("button",{name:"Acknowledge write quorum lost",exact:true}).click();
  await panel.getByLabel("Investigation note").fill("Investigating this scoped incident");
  await panel.getByRole("button",{name:"Confirm acknowledgement",exact:true}).click();
  await expect(panel.getByText("Active alerts (1)",{exact:true})).toBeVisible();
  await expect(panel.getByText("· Acknowledged",{exact:false})).toBeVisible();
  expect(state.writes).toEqual([{expected_revision:1,reason:"Investigating this scoped incident"}]);
  await page.getByRole("button",{name:"List view",exact:true}).click();
  await page.getByRole("button",{name:`Inspect ${nodes[0].hostname}`,exact:true}).click();
  const inspector = isMobile ? page.getByRole("dialog") : page.getByRole("complementary",{name:`Node inspector: ${nodes[0].hostname}`});
  await expect(inspector.getByText("15.2%",{exact:true})).toBeVisible();
  await page.screenshot({path:info.outputPath("monitoring-inspector.png"),fullPage:true});
});

test("Native SSE resync refreshes the snapshot without per-node polling", async ({ page, api }) => {
  const { monitoring:state } = monitoring(api); state.sse = true;
  await page.goto("/admin/infrastructure/connections");
  await expect(page.getByLabel("Storage monitoring",{exact:true}).getByText("Monitoring: critical",{exact:true})).toBeVisible();
  expect(api.requests.some((item) => item.path.endsWith("/telemetry/stream/"))).toBe(true);
  expect(api.requests.filter((item) => /\/nodes\/[^/]+\/$/.test(item.path))).toEqual([]);
  expect(state.reads).toBeGreaterThanOrEqual(2);
});

test("Unconfigured monitoring reports unknown and revoked access clears old measurements", async ({ page, api }) => {
  const { monitoring:state } = monitoring(api); state.configured = false;
  await page.goto("/admin/infrastructure/connections");
  const panel = page.getByLabel("Storage monitoring",{exact:true});
  await expect(panel.getByText("Monitoring has not been configured",{exact:false})).toBeVisible();
  state.configured = true;
  await panel.getByRole("button",{name:"Refresh monitoring",exact:true}).click();
  await expect(panel.getByText("512 GiB",{exact:true})).toBeVisible();
  state.denied = true;
  await panel.getByRole("button",{name:"Refresh monitoring",exact:true}).click();
  await expect(panel.getByText("Monitoring access is no longer available.",{exact:true})).toBeVisible();
  await expect(panel.getByText("512 GiB",{exact:true})).toHaveCount(0);
});
