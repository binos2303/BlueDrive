import { test } from "node:test";
import assert from "node:assert/strict";
import { currentTelemetry, nodeTelemetryHealth } from "./telemetry-model.ts";

const now = Date.now();
const health = { status: "healthy", source: "prometheus:fixture", observed_at: new Date(now).toISOString(), stale: false };
const data = { cluster_id: "fixture", configured: true, revision: 1, event_id: "fixture:1:0", health, expires_at: new Date(now+90_000).toISOString(), cluster_metrics: { usable_free_bytes: 123 }, nodes: { node: { health, metrics: { node_cpu_percent: 15 } } }, alerts: [], sse_available: true, poll_seconds: 30 };

test("Expiry and network failure clear healthy without fabricating zero metrics", () => {
  assert.equal(currentTelemetry(data,now),data);
  for (const result of [currentTelemetry(data,now+91_000),currentTelemetry(data,now,true)]) {
    assert.equal(result?.health.status,"unknown");
    assert.equal(result?.nodes.node.health.stale,true);
    assert.equal(result?.cluster_metrics.usable_free_bytes,123);
    assert.equal(result?.nodes.node.metrics.node_cpu_percent,15);
  }
  assert.equal(data.health.status,"healthy");
});
test("Missing node measurements cannot inherit a healthy cluster badge", () => {
  assert.equal(nodeTelemetryHealth(data,"unreported").status,"unknown");
  assert.equal(currentTelemetry(null,now),null);
});
