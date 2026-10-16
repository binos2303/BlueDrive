import type { UploadStatus, UploadTask } from "./upload-manager-model";
import { AccountServiceError, accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";

export type UploadProgressReport = {
  uploadedBytes: number;
  totalBytes: number;
  bytesPerSecond?: number;
  etaSeconds?: number;
};

export type UploadFailure = {
  message: string;
  retryable: boolean;
  action?: string;
};

export type UploadObserver = {
  onStatus: (
    status: Extract<UploadStatus, "preparing" | "uploading" | "verifying" | "scanning">,
    uploadSessionId?: string,
  ) => void;
  onProgress: (progress: UploadProgressReport) => void;
  /** Call only after the object is complete and all required verification/scanning checks pass. */
  onCompleted: () => void;
};

export interface UploadService {
  readonly connected: boolean;
  readonly supportsPauseResume: boolean;
  /** Reports actual protocol states; resolving without onCompleted is treated as failure. */
  upload(task: UploadTask, file: File, observer: UploadObserver, signal: AbortSignal): Promise<void>;
  /** Must preserve and operate on the upload session ID held by the task. */
  pause?(task: UploadTask): Promise<void>;
  resume?(task: UploadTask): Promise<void>;
}

export class UploadServiceUnavailableError extends Error {
  readonly retryable = false;
  readonly action = "Wait until an upload service is configured, then select the file again.";

  constructor() {
    super("Upload service is not connected.");
    this.name = "UploadServiceUnavailableError";
  }
}

export const notConnectedUploadService: UploadService = {
  connected: false,
  supportsPauseResume: false,
  async upload() {
    throw new UploadServiceUnavailableError();
  },
};

const PART_SIZE = 8 * 1024 * 1024;
const PART_CONCURRENCY = 3;
const PART_RETRIES = 3;
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const readSessionValue = (key: string) => {
  try { return typeof window === "undefined" ? null : window.localStorage.getItem(key); } catch { return null; }
};
const saveSessionValue = (key: string, value: string) => {
  try { if (typeof window !== "undefined") window.localStorage.setItem(key, value); } catch { /* Resume is optional when browser storage is unavailable. */ }
};
const removeSessionValue = (key: string) => {
  try { if (typeof window !== "undefined") window.localStorage.removeItem(key); } catch { /* No saved resume state to remove. */ }
};

type UploadSessionResponse = { upload_id: string; state: string; part_size: number };
type PartAuthorization = { url: string; method: "PUT"; headers: Record<string, string>; expires_in: number };
type AuthorizedPart = PartAuthorization & { part_number: number };

function uploadPart(url: string, headers: Record<string, string>, blob: Blob, signal: AbortSignal,
  report: (loaded: number) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.timeout = 120_000;
    Object.entries(headers).forEach(([name, value]) => xhr.setRequestHeader(name, value));
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) report(event.loaded); };
    xhr.onload = () => {
      const etag = xhr.getResponseHeader("ETag");
      if (xhr.status >= 200 && xhr.status < 300 && etag) resolve(etag);
      else reject(Object.assign(new Error(`Storage part upload failed (${xhr.status}).`), {
        status: xhr.status,
        retryable: [408, 429, 500, 502, 503, 504].includes(xhr.status) || xhr.status === 403,
      }));
    };
    xhr.onerror = () => reject(Object.assign(new Error("Network interrupted during part upload."), { retryable: true }));
    xhr.ontimeout = () => reject(Object.assign(new Error("Upload part timed out."), { retryable: true }));
    xhr.onabort = () => reject(new DOMException("Upload canceled", "AbortError"));
    signal.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(blob);
  });
}

async function sha256Hex(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function authorize(uploadId: string, part: number): Promise<PartAuthorization> {
  // Single-part fallback is used only when a previously issued batch URL expires.
  return requestUploadApi<PartAuthorization>(`/files/api/uploads/${uploadId}/parts/${part}/authorization/`, {
    method: "POST", headers: await accountCsrfHeaders(),
  });
}

async function authorizeBatch(uploadId: string, partNumbers: number[]): Promise<AuthorizedPart[]> {
  if (partNumbers.length === 0) return [];
  const response = await requestUploadApi<{ parts: AuthorizedPart[] }>(
    `/files/api/uploads/${uploadId}/parts/authorizations/`,
    {
      method: "POST",
      headers: { ...(await accountCsrfHeaders()), "Content-Type": "application/json" },
      body: JSON.stringify({ part_numbers: partNumbers }),
    },
  );
  const authorized = new Map(response.parts.map((part) => [part.part_number, part]));
  if (partNumbers.some((partNumber) => !authorized.has(partNumber))) {
    throw new Error("Storage authorization did not include every requested upload part.");
  }
  return partNumbers.map((partNumber) => authorized.get(partNumber)!);
}

async function requestUploadApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    return await requestAccountApi<T>(path, init);
  } catch (error) {
    if (error instanceof AccountServiceError && [408, 429, 500, 502, 503, 504].includes(error.status ?? 0)) {
      throw Object.assign(error, { retryable: true, action: "Retry this upload; completed parts can be sent again safely." });
    }
    throw error;
  }
}

export const djangoMultipartUploadService: UploadService = {
  connected: true,
  supportsPauseResume: false,
  async upload(task, file, observer, signal) {
    observer.onStatus("preparing", task.uploadSessionId ?? undefined);
    const resumeKey = `securedrive-upload:${encodeURIComponent(file.name)}:${file.size}:${file.lastModified}`;
    const fileSha256 = await sha256Hex(file);
    if (signal.aborted) return;
    let uploadId = task.uploadSessionId ?? readSessionValue(resumeKey);
    let alreadyCompleting = false;
    if (uploadId) {
      try {
        const state = await requestUploadApi<{ state: string; expected_sha256: string }>(`/files/api/uploads/${uploadId}/`);
        if (state.expected_sha256 !== fileSha256) {
          try { await requestUploadApi(`/files/api/uploads/${uploadId}/abort/`, { method: "POST", headers: await accountCsrfHeaders() }); } catch { /* Expiry cleanup remains available. */ }
          uploadId = null;
        }
        if (!uploadId) throw new AccountServiceError("Stored upload session belongs to a different file.", 404);
        if (state.state === "available" || state.state === "completed") {
          observer.onStatus("uploading", uploadId);
          observer.onStatus("verifying", uploadId);
          observer.onCompleted();
          removeSessionValue(resumeKey);
          return;
        }
        alreadyCompleting = state.state === "verifying" || state.state === "scanning";
        if (state.state !== "uploading" && !alreadyCompleting) uploadId = null;
      } catch (error) {
        if (error instanceof AccountServiceError && error.status === 404) uploadId = null;
        else throw error;
      }
      if (!uploadId) {
        removeSessionValue(resumeKey);
        removeSessionValue(`${resumeKey}:idempotency`);
      }
    }
    if (!uploadId) {
      let idempotency = readSessionValue(`${resumeKey}:idempotency`);
      if (!idempotency) {
        idempotency = crypto.randomUUID();
        saveSessionValue(`${resumeKey}:idempotency`, idempotency);
      }
      const created = await requestUploadApi<UploadSessionResponse>("/files/api/uploads/", {
        method: "POST", headers: { ...(await accountCsrfHeaders()), "Idempotency-Key": idempotency },
        body: JSON.stringify({ name: file.name, size_bytes: file.size, sha256: fileSha256, folder_id: task.destinationId }),
      });
      uploadId = created.upload_id;
    }
    saveSessionValue(resumeKey, uploadId);
    observer.onStatus("uploading", uploadId);
    if (alreadyCompleting) observer.onStatus("verifying", uploadId);
    const count = Math.ceil(file.size / PART_SIZE);
    const authorizedParts = new Map<number, PartAuthorization>();
    if (!alreadyCompleting && count > 0) {
      const batch = await authorizeBatch(uploadId!, Array.from({ length: count }, (_, index) => index + 1));
      batch.forEach((part) => authorizedParts.set(part.part_number, part));
    }
    const completed = new Map<number, string>();
    const loadedByPart = new Map<number, number>();
    let next = 1;
    let fatal: unknown;
    const worker = async () => {
      while (!signal.aborted && !fatal) {
        const partNumber = next++;
        if (partNumber > count) return;
        const start = (partNumber - 1) * PART_SIZE;
        const part = file.slice(start, Math.min(file.size, start + PART_SIZE));
        for (let attempt = 0; attempt <= PART_RETRIES; attempt++) {
          try {
            const permission = authorizedParts.get(partNumber);
            if (!permission) throw new Error(`Missing storage authorization for part ${partNumber}.`);
            const etag = await uploadPart(permission.url, permission.headers, part, signal, (loaded) => {
              loadedByPart.set(partNumber, loaded);
              observer.onProgress({ uploadedBytes: [...loadedByPart.values()].reduce((a, b) => a + b, 0), totalBytes: file.size });
            });
            completed.set(partNumber, etag);
            loadedByPart.set(partNumber, part.size);
            observer.onProgress({ uploadedBytes: [...loadedByPart.values()].reduce((a, b) => a + b, 0), totalBytes: file.size });
            break;
          } catch (error) {
            if (signal.aborted) throw error;
            if (attempt === PART_RETRIES || (error as { retryable?: boolean }).retryable !== true) { fatal = error; return; }
            loadedByPart.delete(partNumber);
            if ((error as { status?: number }).status === 403) {
              const refreshed = await authorize(uploadId!, partNumber);
              authorizedParts.set(partNumber, refreshed);
            }
            await sleep(Math.min(2000, 200 * (2 ** attempt) + Math.random() * 150));
          }
        }
      }
    };
    if (!alreadyCompleting) {
      try {
        await Promise.all(Array.from({ length: Math.min(PART_CONCURRENCY, count) }, worker));
      } catch (error) {
        if (!signal.aborted) throw error;
      }
    }
    if (signal.aborted) {
      try {
        await requestUploadApi(`/files/api/uploads/${uploadId}/abort/`, {
          method: "POST", headers: await accountCsrfHeaders(),
        });
      } catch {
        // Session expiry cleanup is the recovery path if the network is already gone.
      }
      removeSessionValue(resumeKey);
      return;
    }
    if (fatal) throw fatal;
    if (!alreadyCompleting) {
      observer.onStatus("verifying", uploadId);
      await requestUploadApi<{ state: string; file_id?: number }>(`/files/api/uploads/${uploadId}/complete/`, {
        method: "POST", headers: await accountCsrfHeaders(),
        body: JSON.stringify({ parts: [...completed].sort(([a], [b]) => a - b).map(([part_number, etag]) => ({ part_number, etag })) }),
      });
    }
    let result: { state: string; file_id?: number; failure_code?: string | null } = { state: "verifying" };
    for (let attempt = 0; attempt < 120; attempt += 1) {
      if (signal.aborted) return;
      result = await requestUploadApi<{ state: string; file_id?: number; failure_code?: string | null }>(`/files/api/uploads/${uploadId}/`);
      if (result.state === "scanning") observer.onStatus("scanning", uploadId);
      else if (result.state === "verifying") observer.onStatus("verifying", uploadId);
      if (result.state === "available" || result.state === "completed" || result.state === "failed") break;
      await sleep(5000);
    }
    if (result.state === "failed") throw Object.assign(new Error("The server rejected this upload during verification or security checks."), { retryable: false, action: "Review the file and select it again after correcting the issue." });
    if (result.state !== "available" && result.state !== "completed") throw Object.assign(new Error("Finalization is still running; retry to resume status polling."), { retryable: true, action: "The server retains this upload session; retry to check its status." });
    removeSessionValue(resumeKey);
    removeSessionValue(`${resumeKey}:idempotency`);
    observer.onCompleted();
  },
  async pause() { /* Browser transport cannot pause an in-flight XHR; abort and resume by overwriting parts. */ },
  async resume() { /* upload() reuses the persisted Django session and re-uploads parts idempotently. */ },
};
