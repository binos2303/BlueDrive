import assert from "node:assert/strict";
import test from "node:test";
import { layoutPositions, matchesHost, topologyGraph } from "./topology-model.ts";
import type { StorageTopologySnapshot } from "../../lib/storage-control-service.ts";

const health = { status: "unknown", source: "not_collected", observed_at: null, stale: true };
const fixture: StorageTopologySnapshot = { cluster: { id: "a", display_name: "Test", slug: "test", state: "draft", provider: "s3" }, cluster_id: "a", revision: 7, observed_at: null, health, pools: [{ id: "p", name: "Pool", generation: 1, desired_status: "active", node_ids: ["one"] }],
  nodes: [{ id: "one", cluster_id: "a", pool_id: "p", hostname: "alpha", private_ips: ["10.0.0.1"], agent_identity: null, inventory_status: "registered", last_seen: null, health, labels: {} },{ id: "two", cluster_id: "a", pool_id: null, hostname: "beta", private_ips: [], agent_identity: null, inventory_status: "maintenance", last_seen: null, health, labels: {} }], disks: [],
  layout: { revision: 3, scope: "personal", positions: { one: { x: 30, y: 80 } }, viewport: { x: 0, y: 0, zoom: 1 } }, layout_revisions: { personal: 3, shared: 0 } };

test("groups are parents first, saved host coordinates stay relative, and snapshot stays immutable", () => {
  const original = structuredClone(fixture);
  const result = topologyGraph(fixture, () => undefined);
  const host = result.nodes.find((node) => node.id === "one")!;
  assert.equal(host.parentId, "pool:p");
  assert.deepEqual(host.position, { x: 30, y: 80 });
  assert.ok(result.nodes.findIndex((node) => node.id === "pool:p") < result.nodes.indexOf(host));
  assert.ok(result.nodes.some((node) => node.id === "pool:unassigned"));
  assert.deepEqual(fixture, original);
  assert.deepEqual(Object.keys(layoutPositions(result.nodes)).sort(), ["one", "two"]);
});

test("auto layout is deterministic and contains no physical mutation fields", () => {
  const first = topologyGraph(fixture, () => undefined, {});
  const second = topologyGraph(fixture, () => undefined, {});
  assert.deepEqual(layoutPositions(first.nodes), layoutPositions(second.nodes));
  for (const value of Object.values(layoutPositions(first.nodes))) assert.deepEqual(Object.keys(value).sort(), ["x", "y"]);
});

test("unknown keys are ignored and obsolete pool dimensions constrain old positions", () => {
  const result = topologyGraph(fixture, () => undefined, { one: { x: 999999, y: -99 }, foreign: { x: 0, y: 0 } });
  assert.equal(result.adjusted, 1);
  assert.equal(result.nodes.some((node) => node.id === "foreign"), false);
});

test("search supports name IP and ID alongside pool and inventory filters", () => {
  assert.ok(matchesHost(fixture.nodes[0], "10.0.0.1", "p", "registered"));
  assert.ok(matchesHost(fixture.nodes[1], "BETA", "unassigned", "maintenance"));
  assert.equal(matchesHost(fixture.nodes[0], "beta", "all", "all"), false);
});

test("large pools get a balanced grid rather than a tall strip", () => {
  const snapshot = { ...fixture, nodes: Array.from({ length: 100 }, (_, i) => ({ ...fixture.nodes[0], id: String(i) })) };
  const group = topologyGraph(snapshot, () => undefined, {}).nodes[0];
  const ratio = Number(group.style?.width) / Number(group.style?.height);
  assert.ok(ratio > .7 && ratio < 2);
});
