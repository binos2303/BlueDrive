"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AccountServiceError } from "@/lib/account-service";
import { storageGet, storageStreamUrl, type StorageTelemetry } from "@/lib/storage-control-service";
import { currentTelemetry } from "./telemetry-model";

export default function useStorageTelemetry(clusterId: string, tenantId: string | undefined, enabled: boolean) {
  const [raw, setRaw] = useState<StorageTelemetry | null>(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState("Loading monitoring");
  const [clock, setClock] = useState(0);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let stream: EventSource | null = null;
    let busy = false, pending = false, denied = false;
    const revoke = () => { denied = true; stream?.close(); setRaw(null); setError("Monitoring access is no longer available."); setMode("Access unavailable"); };
    async function load() {
      if (denied || controller.signal.aborted) return;
      if (busy) { pending = true; return; }
      busy = true;
      try {
        const result = await storageGet<StorageTelemetry>({ tenantId }, `clusters/${clusterId}/telemetry/`, controller.signal);
        if (controller.signal.aborted || denied) return;
        if (result.cluster_id !== clusterId) throw new Error("Monitoring response does not match this storage.");
        setRaw(result); setClock(Date.now()); setError("");
        if (result.sse_available && typeof EventSource !== "undefined") {
          if (!stream) {
            stream = new EventSource(storageStreamUrl({ tenantId }, clusterId), { withCredentials: true });
            stream.addEventListener("resync", () => { setMode("Live updates"); void load(); });
            stream.addEventListener("access_revoked", revoke);
            stream.onopen = () => { if (!denied) setMode("Live updates"); };
            stream.onerror = () => { if (!denied && !controller.signal.aborted) setMode("Reconnecting · polling every 30 seconds"); };
          }
        } else { stream?.close(); stream = null; setMode("Polling every 30 seconds"); }
      } catch (cause) {
        if (controller.signal.aborted) return;
        if (cause instanceof AccountServiceError && [401,403,404].includes(cause.status ?? 0)) revoke();
        else { setError("Could not refresh monitoring. Last known values are marked stale; retry or wait for reconnection."); setMode("Connection unavailable"); }
      } finally { busy = false; if (pending) { pending = false; void load(); } }
    }
    void load();
    const poll = window.setInterval(() => void load(), 30_000);
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => { controller.abort(); stream?.close(); window.clearInterval(poll); window.clearInterval(timer); };
  }, [clusterId, tenantId, enabled, retry]);
  const refresh = useCallback(() => setRetry((value) => value + 1), []);
  const data = useMemo(() => enabled ? currentTelemetry(raw, clock, Boolean(error)) : null, [raw, clock, error, enabled]);
  return { data, error, mode, refresh };
}
