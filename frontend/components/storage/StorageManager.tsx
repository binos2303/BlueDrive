"use client";

import { useState, type ReactNode } from "react";
import StorageConnections from "./StorageConnections";
import StorageTopology from "./StorageTopology";

export default function StorageManager({ tenantId, fallback }: { tenantId?: string; fallback?: ReactNode }) {
  const [dirty, setDirty] = useState(false);
  return <StorageConnections tenantId={tenantId} fallback={fallback} hasUnsavedLayout={dirty} renderTopology={(cluster, caps) => <StorageTopology key={`${tenantId ?? "platform"}:${cluster.id}`} clusterId={cluster.id} tenantId={tenantId} canConfigure={caps.permissions["storage.configure"] === true} monitoringEnabled={caps.monitoring_enabled === true && caps.permissions["storage.monitor"] === true} onDirtyChange={setDirty} />} />;
}
