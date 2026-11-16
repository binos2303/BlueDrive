import type { StorageHealth, StorageTelemetry } from "../../lib/storage-control-service";

export function currentTelemetry(data: StorageTelemetry | null, now: number, disconnected = false): StorageTelemetry | null {
  if (!data) return null;
  const expired = !data.expires_at || !Number.isFinite(Date.parse(data.expires_at)) || Date.parse(data.expires_at) < now;
  if (!disconnected && !expired && !data.health.stale) return data;
  const unknown = (health: StorageHealth): StorageHealth => ({ ...health, status: "unknown", stale: true, reason_code: disconnected ? "connection_unavailable" : expired ? "samples_stale" : health.reason_code || "samples_stale" });
  return { ...data, health: unknown(data.health), nodes: Object.fromEntries(Object.entries(data.nodes).map(([id, node]) => [id, { ...node, health: unknown(node.health) }])) };
}

export function nodeTelemetryHealth(data: StorageTelemetry, id: string): StorageHealth {
  return data.nodes[id]?.health ?? { ...data.health, status: "unknown", reason_code: "node_samples_missing" };
}
