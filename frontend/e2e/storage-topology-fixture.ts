import type { Route } from "@playwright/test";
import { expect, type MockApi } from "./mocked-api";
const clusterId = "10000000-0000-4000-8000-000000000000";
const poolId = "20000000-0000-4000-8000-000000000000";
const health = { status: "unknown", source: "not_collected", observed_at: null, stale: true };
export function setup(api: MockApi, count = 3, organization = false) {
  api.admin = !organization; api.business = organization;
  const base = organization ? "/accounts/api/tenants/tenant-test/storage/" : "/accounts/api/admin/storage/";
  const cluster = { id: clusterId, display_name: "Recorded storage", slug: "recorded", state: "draft", provider: "s3" };
  const nodes = Array.from({ length: count }, (_, i) => ({ id: `30000000-0000-4000-8000-${String(i).padStart(12, "0")}`, cluster_id: clusterId, pool_id: i === 2 ? null : poolId, hostname: `storage-${String(i).padStart(3, "0")}`, private_ips: [`10.31.0.${i + 1}`], agent_identity: null, inventory_status: i === 1 ? "maintenance" : "registered", last_seen: null, labels: {}, health }));
  const disk = { id: "disk-fixture", node_id: nodes[0]?.id, stable_disk_id: "recorded-disk-1", mount_path: "/mnt/storage", capacity_bytes: 1024 ** 3, capacity_source: "inventory", inventory_status: "registered", last_seen: null, health };
  const state = { fail: false, conflict: false, tooLarge: false, layout: { revision: 0, scope: "personal", positions: {} as Record<string, { x: number; y: number }>, viewport: { x: 0, y: 0, zoom: 1 } }, writes: [] as Record<string, unknown>[] };
  const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body, headers: { "access-control-allow-origin": route.request().headers().origin || "http://localhost:3000", "access-control-allow-credentials": "true" } });
  api.override(base + "capabilities/", (route) => reply(route, { permissions: { "storage.view": true, "storage.configure": false }, topology_enabled: true, routing_enabled: false, lab_probes_enabled: false }));
  api.override(base + "clusters/", (route) => reply(route, { results: [cluster], count: 1, page: 1, has_more: false }));
  api.override(`${base}clusters/${clusterId}/connections/`, (route) => reply(route, { results: [], count: 0, page: 1, has_more: false }));
  api.override(`${base}clusters/${clusterId}/topology/`, (route) => state.fail ? reply(route, { detail: "Inventory temporarily unavailable." }, 503) : state.tooLarge ? reply(route, { detail: "Use the paginated node list for this cluster." }, 422) : reply(route, { cluster, cluster_id: clusterId, revision: 74, observed_at: null, health, pools: [{ id: poolId, name: "Pool A", generation: 1, desired_status: "registered", node_ids: nodes.filter((node) => node.pool_id).map((node) => node.id) }], nodes, disks: count ? [disk] : [], layout: state.layout, layout_revisions: { personal: state.layout.revision, shared: 0 } }));
  api.override(`${base}clusters/${clusterId}/nodes/`, (route) => {
    const url = new URL(route.request().url()); const page = Number(url.searchParams.get("page") || 1);
    const filtered = nodes.filter((node) => node.hostname.includes(url.searchParams.get("q") || ""));
    return reply(route, { results: filtered.slice((page - 1) * 50, page * 50), count: filtered.length, page, has_more: page * 50 < filtered.length });
  });
  for (const node of nodes) api.override(`${base}clusters/${clusterId}/nodes/${node.id}/`, (route) => reply(route, { ...node, disk_count: node.id === nodes[0].id ? 1 : 0 }));
  api.override(`${base}clusters/${clusterId}/disks/`, (route) => reply(route, { results: new URL(route.request().url()).searchParams.get("node_id") === nodes[0]?.id ? [disk] : [], count: 1, page: 1, has_more: false }));
  api.override(`${base}clusters/${clusterId}/events/`, (route) => reply(route, { results: [], count: 0, page: 1, has_more: false }));
  api.override(`${base}clusters/${clusterId}/layout/`, (route) => {
    const body = route.request().postDataJSON();
    expect(Object.keys(body).sort()).toEqual(["expected_revision", "positions", "scope", "viewport"]);
    state.writes.push(body);
    if (state.conflict) return reply(route, { detail: "Layout changed in another window. Reload the saved layout before retrying." }, 409);
    expect(body.expected_revision).toBe(state.layout.revision);
    expect(body.scope).toBe("personal");
    state.layout = { ...body, revision: state.layout.revision + 1 };
    return reply(route, { layout: state.layout, unchanged: false });
  });
  return { base, nodes, state };
}
