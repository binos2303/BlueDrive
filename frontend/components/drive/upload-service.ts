import type { UploadStatus, UploadTask } from "./upload-manager-model";
import { UploadTransferControl } from "./upload-transfer-control";
import { UploadPartProgress } from "./upload-progress-model";
import { UploadProgressTelemetry } from "./upload-progress-telemetry";
import { OnDemandPartAuthorizer } from "./upload-part-authorization";
import { sha256File } from "./upload-file-hash";
export { UploadPausedError } from "./upload-transfer-control";
import { reconcilePartReceipts, restorePartReceipts, serializePartReceipts, type ProviderPart } from "./upload-resume-model";
import { AccountServiceError, accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import { getActiveWorkspaceIdForRequest } from "@/lib/workspace-context";

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
  /** Abort a paused server session and release its reserved quota. */
  cancelPaused?(task: UploadTask, file: File): Promise<void>;
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
// Limit URL age: the backend currently signs each part for only 180 seconds.
const AUTHORIZATION_BATCH_SIZE = 6;
const activeTransfers = new Map<string, UploadTransferControl>();
function resumeStorageKey(task: UploadTask, file: File): string {
  const workspaceScope = getActiveWorkspaceIdForRequest() ?? "default";
  const destinationScope = task.destinationId ?? "root";
  return `securedrive-upload:${workspaceScope}:${encodeURIComponent(destinationScope)}:${encodeURIComponent(file.name)}:${file.size}:${file.lastModified}`;
}
function forgetResumeState(key: string): void {
  removeSessionValue(key);
  removeSessionValue(`${key}:idempotency`);
  removeSessionValue(`${key}:parts`);
}
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
    if (signal.aborted) {
      reject(new DOMException("Upload canceled", "AbortError"));
      return;
    }
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
    const onAbort = () => xhr.abort();
    signal.addEventListener("abort", onAbort, { once: true });
    xhr.onloadend = () => signal.removeEventListener("abort", onAbort);
    if (signal.aborted) {
      signal.removeEventListener("abort", onAbort);
      reject(new DOMException("Upload canceled", "AbortError"));
      return;
    }
    xhr.send(blob);
  });
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

async function fetchReconciledPartReceipts(
  uploadId: string,
  fileSize: number,
  receipts: ReadonlyMap<number, string>,
): Promise<Map<number, string>> {
  if (!receipts.size) return new Map();
  const response = await requestUploadApi<{ parts: ProviderPart[] }>(`/files/api/uploads/${uploadId}/parts/`);
  return reconcilePartReceipts(receipts, response.parts, fileSize, PART_SIZE);
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
  supportsPauseResume: true,
  async upload(task, file, observer, signal) {
    if (activeTransfers.has(task.id)) throw new Error("Upload task already has an active transfer.");
    const control = new UploadTransferControl(signal);
    activeTransfers.set(task.id, control);
    try {
    observer.onStatus("preparing", task.uploadSessionId ?? undefined);
    // A file with the same name/size can be uploaded to different folders.
    const resumeKey = resumeStorageKey(task, file);
    // Abort during hashing must not allocate a new UploadSession. If this is a
    // resumed task, release its existing reservation on *cancel* (not pause).
    const cancelBeforeUpload = async () => {
      const existingSession = task.uploadSessionId ?? readSessionValue(resumeKey);
      if (existingSession) {
        try {
          await requestUploadApi(`/files/api/uploads/${existingSession}/abort/`, {
            method: "POST", headers: await accountCsrfHeaders(),
          });
        } catch { /* Expiry/reconciliation will clean up on network failure. */ }
      }
      forgetResumeState(resumeKey);
    };
    let fileSha256: string;
    try {
      fileSha256 = await sha256File(file, { signal: control.signal });
    } catch (error) {
      control.throwIfPaused();
      if (signal.aborted) {
        await cancelBeforeUpload();
        return;
      }
      throw error;
    }
    control.throwIfPaused();
    if (signal.aborted) {
      await cancelBeforeUpload();
      return;
    }
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
          removeSessionValue(`${resumeKey}:idempotency`);
          removeSessionValue(`${resumeKey}:parts`);
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
    const count = Math.ceil(file.size / PART_SIZE);
    const receiptsKey = `${resumeKey}:parts`;
    // Receipts originate from successful XHR responses. Never store presigned URLs.
    // The server independently validates the manifest against MinIO ListParts.
    const savedReceipts = alreadyCompleting ? new Map<number, string>()
      : restorePartReceipts(readSessionValue(receiptsKey), uploadId, count);
    // A previously uploaded part can disappear or be overwritten by another tab.
    // Reuse only receipts still confirmed by the storage provider.
    const completed = alreadyCompleting ? savedReceipts
      : await fetchReconciledPartReceipts(uploadId, file.size, savedReceipts);
    if (savedReceipts.size > 0) {
      saveSessionValue(receiptsKey, serializePartReceipts(uploadId, completed));
    }
    const progress = new UploadPartProgress(file.size, PART_SIZE);
    completed.forEach((_etag, number) => progress.update(number, PART_SIZE));
    const telemetry = new UploadProgressTelemetry(file.size, progress.uploadedBytes);
    const updatePartProgress = (number: number, loaded: number, force = false) => {
      const uploadedBytes = progress.update(number, loaded);
      const report = telemetry.report(uploadedBytes, force);
      if (report) observer.onProgress(report);
    };
    observer.onStatus("uploading", uploadId);
    if (alreadyCompleting) observer.onStatus("verifying", uploadId);
    else if (completed.size > 0) {
      const report = telemetry.report(progress.uploadedBytes, true);
      if (report) observer.onProgress(report);
    }
    const pending = Array.from({ length: count }, (_, index) => index + 1)
      .filter((number) => !completed.has(number));
    // Workers request each small batch just before use rather than minting all
    // short-lived URLs at once (especially useful on slow or paused uploads).
    const partAuthorizations = new OnDemandPartAuthorizer<AuthorizedPart>(
      pending, AUTHORIZATION_BATCH_SIZE,
      (numbers) => authorizeBatch(uploadId!, numbers),
    );
    let next = 0;
    let fatal: unknown;
    const worker = async () => {
      while (!control.signal.aborted && !fatal) {
        const partNumber = pending[next++];
        if (partNumber === undefined) return;
        const start = (partNumber - 1) * PART_SIZE;
        const part = file.slice(start, Math.min(file.size, start + PART_SIZE));
        for (let attempt = 0; attempt <= PART_RETRIES; attempt++) {
          try {
            const permission = await partAuthorizations.get(partNumber, control.signal);
            const etag = await uploadPart(permission.url, permission.headers, part, control.signal, (loaded) => {
              updatePartProgress(partNumber, loaded);
            });
            completed.set(partNumber, etag);
            saveSessionValue(receiptsKey, serializePartReceipts(uploadId!, completed));
            updatePartProgress(partNumber, part.size, true);
            break;
          } catch (error) {
            if (control.signal.aborted) throw error;
            if (attempt === PART_RETRIES || (error as { retryable?: boolean }).retryable !== true) { fatal = error; return; }
            updatePartProgress(partNumber, 0, true);
            if ((error as { status?: number }).status === 403) {
              const refreshed = await authorize(uploadId!, partNumber);
              partAuthorizations.replace({ part_number: partNumber, ...refreshed });
            }
            await sleep(Math.min(2000, 200 * (2 ** attempt) + Math.random() * 150));
          }
        }
      }
    };
    if (!alreadyCompleting) {
      // Wait for every interrupted PUT to settle before exposing Resume.
      const outcomes = await Promise.allSettled(
        Array.from({ length: Math.min(PART_CONCURRENCY, pending.length) }, worker),
      );
      control.throwIfPaused();
      if (!signal.aborted) {
        const rejected = outcomes.find((outcome) => outcome.status === "rejected");
        if (rejected?.status === "rejected") throw rejected.reason;
      }
    }
    // Pause preserves the server-side UploadSession and its uploaded parts.
    // Do not call the Django abort endpoint or discard the saved receipts.
    control.throwIfPaused();
    if (signal.aborted) {
      try {
        await requestUploadApi(`/files/api/uploads/${uploadId}/abort/`, {
          method: "POST", headers: await accountCsrfHeaders(),
        });
      } catch {
        // Session expiry cleanup is the recovery path if the network is already gone.
      }
      removeSessionValue(resumeKey);
      removeSessionValue(`${resumeKey}:idempotency`);
      removeSessionValue(receiptsKey);
      return;
    }
    if (fatal) throw fatal;
    if (!alreadyCompleting) {
      control.throwIfPaused();
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
    removeSessionValue(receiptsKey);
    observer.onCompleted();
    } finally {
      activeTransfers.delete(task.id);
      control.finish();
    }
  },
  async pause(task) {
    const transfer = activeTransfers.get(task.id);
    if (!transfer) throw new Error("There is no active upload to pause.");
    transfer.pause();
    await transfer.finished;
  },
  async resume(task) {
    if (activeTransfers.has(task.id)) throw new Error("The previous upload has not stopped yet.");
    // UploadManager schedules upload() again. That method verifies the saved
    // UploadSession/receipt manifest against the provider before sending parts.
  },
  async cancelPaused(task, file) {
    if (!task.uploadSessionId) throw new Error("Paused upload has no server session to cancel.");
    if (activeTransfers.has(task.id)) throw new Error("Cannot cancel while an upload is still stopping.");
    await requestUploadApi(`/files/api/uploads/${task.uploadSessionId}/abort/`, {
      method: "POST", headers: await accountCsrfHeaders(),
    });
    forgetResumeState(resumeStorageKey(task, file));
  },
};
