import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";

export type StorageScope = { tenantId: string } | { tenantId?: undefined };
export type StorageCapabilities = {
  permissions: Record<string, boolean>; routing_enabled: boolean; lab_probes_enabled: boolean; runtime_probes_enabled?: boolean; topology_enabled?: boolean; monitoring_enabled?: boolean;
};
export type StorageCluster = { id: string; display_name: string; slug: string; state: string; provider: string };
export type ConnectionProfile = { id: string; label: string; endpoint_url: string; public_endpoint_url: string; provider: string; lab: boolean };
export type StorageConnection = {
  id: string; cluster_id: string; revision: number; profile_id: string; endpoint_url: string;
  public_endpoint_url: string; bucket: string; state: string; last_error_code: string | null;
  verified_at: string | null; read_verified_at: string | null; verification_scope: "lab" | "read_only" | "runtime";
};
export type StorageProbe = { id: string; mode?: "lab" | "runtime"; state: string; expired: boolean; expires_at: string; error_code: string | null; cleanup_bucket: string | null; checks: Record<string, boolean> };
export type StorageBinding = { connection_id: string | null; generation: number; cluster_id?: string };
export type StoragePage<T> = { results: T[]; count: number; page: number; has_more: boolean };
export type ProbeChallenge = {
  probe: StorageProbe;
  authorization?: { url: string; expires_in: number };
  upload_authorization?: {
    url: string; method: string; headers: Record<string, string>;
    body_base64: string; expires_in: number;
  };
};

export type StorageHealth = { status: string; source: string; observed_at: string | null; last_success_at?: string | null; stale: boolean; reason_code?: string };
export type StorageAlert = { id: string; cluster_id: string; code: string; severity: string; revision: number; first_seen_at: string; last_seen_at: string; resolved_at: string | null; acknowledged_at: string | null; acknowledged_by: number | null };
export type StorageTelemetry = { cluster_id: string; configured: boolean; revision: number; event_id: string; health: StorageHealth; expires_at: string | null; cluster_metrics: Record<string,number>; nodes: Record<string,{ health: StorageHealth; metrics: Record<string,number> }>; alerts: StorageAlert[]; sse_available: boolean; poll_seconds: number };

export function storageStreamUrl(scope: StorageScope, clusterId: string) {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!base) throw new Error("Storage service is unavailable.");
  return base.replace(/\/+$/, "") + storageBase(scope) + `clusters/${encodeURIComponent(clusterId)}/telemetry/stream/`;
}
export type StorageHost = { id: string; cluster_id: string; pool_id: string | null; hostname: string; private_ips: string[]; agent_identity: string | null; inventory_status: string; last_seen: string | null; health: StorageHealth; labels: Record<string,string> };
export type StorageDisk = { id: string; node_id: string; stable_disk_id: string; mount_path: string; capacity_bytes: number | null; capacity_source: string; inventory_status: string; last_seen: string | null; health: StorageHealth };
export type StoragePool = { id: string; name: string; generation: number; desired_status: string; node_ids: string[] };
export type StorageLayout = { revision: number; scope: "personal" | "shared"; positions: Record<string, { x: number; y: number }>; viewport: { x: number; y: number; zoom: number } };
export type StorageTopologySnapshot = { cluster: StorageCluster; cluster_id: string; revision: number; observed_at: string | null; health: StorageHealth; pools: StoragePool[]; nodes: StorageHost[]; disks: StorageDisk[]; layout: StorageLayout; layout_revisions: Record<"personal" | "shared",number> };

export function storageBase(scope: StorageScope) {
  return scope.tenantId ? `/accounts/api/tenants/${encodeURIComponent(scope.tenantId)}/storage/` : "/accounts/api/admin/storage/";
}

export function storageGet<T>(scope: StorageScope, path: string, signal?: AbortSignal) {
  return requestAccountApi<T>(storageBase(scope) + path, { cache: "no-store", signal });
}

export async function storageWrite<T>(scope: StorageScope, path: string, body: unknown, method = "POST", key?: string) {
  const headers = await accountCsrfHeaders();
  if (key) headers["Idempotency-Key"] = key;
  return requestAccountApi<T>(storageBase(scope) + path, { method, headers, body: JSON.stringify(body) });
}

export function connectionPath(connection: StorageConnection) {
  return `clusters/${connection.cluster_id}/connections/${connection.id}/`;
}

/** Chỉ dùng origin storage đã duyệt; không cho credential hay redirect chuyển sang origin khác. */
function approvedChallengeUrl(connection: StorageConnection, value: string): URL {
  let url: URL;
  let approved: URL;
  try {
    url = new URL(value);
    approved = new URL(connection.public_endpoint_url);
  } catch {
    // Không đưa signed query string vào thông báo lỗi.
    throw new Error("The storage verification address is not approved.");
  }
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) || url.hostname.endsWith(".localhost");
  if (url.origin !== approved.origin || url.username || url.password || url.hash ||
      (url.protocol !== "https:" && !(url.protocol === "http:" && local))) {
    throw new Error("The storage verification address is not approved.");
  }
  return url;
}

/** Chỉ lấy 64 bytes mẫu từ origin đã duyệt; không gửi cookie hay tự theo redirect. */
export async function checkStorageChallenge(connection: StorageConnection, challenge: ProbeChallenge): Promise<string> {
  if (!challenge.authorization || challenge.probe.expired || challenge.probe.state !== "awaiting_browser") throw new Error("The verification sample has expired. Clean it up and start again.");
  const url = approvedChallengeUrl(connection, challenge.authorization.url);
  const response = await fetch(url, { credentials: "omit", redirect: "error", referrerPolicy: "no-referrer", cache: "no-store", signal: AbortSignal.timeout(15_000) });
  if (!response.ok || !response.body) throw new Error("Could not read the verification sample. Check the storage browser endpoint and retry.");
  const reader = response.body.getReader();
  const bytes = new Uint8Array(64);
  let size = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      if (size + chunk.value.length > 64) throw new Error("The verification sample has an unexpected size.");
      bytes.set(chunk.value, size);
      size += chunk.value.length;
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
  if (size !== 64) throw new Error("The verification sample is incomplete. Retry the browser check.");
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (value) => value.toString(16).padStart(2, "0")).join("");
}


/** Kiểm thử runtime: multipart PUT của browser + GET đối chiếu, không cấp quyền tạo bucket. */
export async function checkRuntimeStorageChallenge(connection: StorageConnection, challenge: ProbeChallenge) {
  const upload = challenge.upload_authorization;
  if (challenge.probe.mode !== "runtime" || !upload || challenge.probe.state !== "awaiting_browser" || challenge.probe.expired || upload.method !== "PUT") {
    throw new Error("The runtime verification sample is not available.");
  }
  const url = approvedChallengeUrl(connection, upload.url);
  if (typeof upload.body_base64 !== "string" || upload.body_base64.length !== 88 || !/^[A-Za-z0-9+/]{86}==$/.test(upload.body_base64)) {
    throw new Error("The runtime verification sample is invalid.");
  }
  const encoded = atob(upload.body_base64);
  if (encoded.length !== 64) throw new Error("The runtime verification sample has an unexpected size.");
  const body = Uint8Array.from(encoded, (character) => character.charCodeAt(0));
  if (!upload.headers || typeof upload.headers !== "object" || Array.isArray(upload.headers)) {
    throw new Error("The signed upload headers are unavailable.");
  }
  const headers = new Headers(upload.headers);
  if (headers.has("cookie") || headers.has("authorization") || headers.has("proxy-authorization")) {
    throw new Error("The runtime verification headers are not approved.");
  }
  const response = await fetch(url, {
    method: "PUT", headers, body,
    credentials: "omit", redirect: "error", referrerPolicy: "no-referrer", cache: "no-store",
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error("The browser could not upload the runtime verification sample.");
  // Multipart completion requires the exact ETag emitted by object storage.
  const etag = response.headers.get("ETag");
  if (!etag || etag.length > 256 || /[\r\n]/.test(etag)) {
    throw new Error("Storage did not expose the multipart ETag. Check its browser CORS policy.");
  }
  const put_sha256 = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", body)),
    (value) => value.toString(16).padStart(2, "0")).join("");
  const sha256 = await checkStorageChallenge(connection, challenge);
  return { sha256, put_sha256, put_etag: etag };
}
