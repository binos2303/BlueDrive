import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import { getActiveWorkspaceIdForRequest } from "@/lib/workspace-context";
import { isPreviewSupported, normalizePreviewMimeType } from "@/lib/file-preview-policy";
import { isExpectedDownloadMimeType } from "@/lib/drive-download-policy";

export type DownloadProgress = { loaded: number; total: number | null };
export type FileDownloadResult = "browser-started" | "received";

export type RenameTarget = { kind: "file" | "folder"; id: number; name: string };
export type RenameResult = RenameTarget & { changed: boolean; detail: string };

export async function renameDriveItem(target: RenameTarget): Promise<RenameResult> {
  return requestAccountApi<RenameResult>("/drive/api/items/rename/", {
    method: "POST",
    headers: await accountCsrfHeaders(),
    body: JSON.stringify(target),
  });
}

export type DriveFileDetails = {
  type: "file";
  name: string;
  size: number;
  mime_type: string;
  owner: string;
  access: string;
  encrypted: boolean;
  location: string;
};

export function getDriveFileDetails(fileId: number): Promise<DriveFileDetails> {
  return requestAccountApi<DriveFileDetails>(`/drive/files/${fileId}/details/`);
}

/** Preview qua Django để giữ kiểm quyền và khả năng đọc file mã hóa legacy. */
export async function fetchDriveFilePreview(fileId: number, signal: AbortSignal): Promise<Blob> {
  const headers = new Headers({ Accept: "application/json, image/*, text/plain" });
  const workspaceId = getActiveWorkspaceIdForRequest();
  if (workspaceId) headers.set("X-Workspace-ID", workspaceId);
  const response = await fetch(`${driveApiBase()}/drive/files/${fileId}/view/`, {
    method: "GET", credentials: "include", headers, signal, cache: "no-store",
  });
  if (!response.ok) {
    let message = `Preview failed (HTTP ${response.status}).`;
    try {
      const json = await response.json() as { detail?: string };
      if (json.detail) message = json.detail;
    } catch { /* Redirect/HTML errors must not be rendered as preview content. */ }
    throw new Error(message);
  }
  const mime = normalizePreviewMimeType(response.headers.get("Content-Type") ?? "");
  if (!isPreviewSupported(mime)) throw new Error("This file cannot be previewed. Download it instead.");
  return response.blob();
}



function driveApiBase(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!base) throw new Error("Drive service is not connected. Configure NEXT_PUBLIC_API_BASE_URL.");
  return base.replace(/\/+$/, "");
}

function filenameFromDisposition(value: string | null, fallback: string): string {
  const utf8 = value?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const quoted = value?.match(/filename="((?:\\.|[^"])*)"/i)?.[1];
  let name = fallback;
  try {
    if (utf8) name = decodeURIComponent(utf8);
    else if (quoted) name = quoted.replace(/\\([\\"])/g, "$1");
  } catch {
    name = fallback;
  }
  return name.replace(/[\\/\u0000-\u001f\u007f]/g, "_").slice(0, 255) || "download";
}

/** Giữ tiến trình và Blob cho file cần giải mã và ZIP qua Django. */
async function downloadDriveBinary(
  path: string,
  fallbackName: string,
  expectedContentType: string,
  onProgress: (progress: DownloadProgress) => void,
): Promise<void> {
  const headers = new Headers({ Accept: `${expectedContentType}, application/json` });
  const workspaceId = getActiveWorkspaceIdForRequest();
  if (workspaceId) headers.set("X-Workspace-ID", workspaceId);
  let response: Response;
  try {
    response = await fetch(`${driveApiBase()}${path}`, {
      credentials: "include", headers,
      cache: "no-store", referrerPolicy: "no-referrer", redirect: "error",
    });
  } catch {
    throw new Error("Could not reach the download service. Check your connection and retry.");
  }
  if (!response.ok) {
    let detail = `Download failed (HTTP ${response.status}).`;
    try {
      const body = await response.json() as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch { /* Giữ thông báo HTTP khi API không trả JSON. */ }
    throw new Error(detail);
  }
  if (!isExpectedDownloadMimeType(response.headers.get("Content-Type"), expectedContentType)) {
    await response.body?.cancel();
    throw new Error("The service returned an unexpected response. No file was saved.");
  }
  const length = Number(response.headers.get("Content-Length"));
  const total = Number.isSafeInteger(length) && length > 0 ? length : null;
  const chunks: BlobPart[] = [];
  let loaded = 0;
  const reader = response.body?.getReader();
  if (!reader) throw new Error("The service returned an empty download response.");
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      loaded += value.byteLength;
      onProgress({ loaded, total });
    }
  } catch {
    await reader.cancel().catch(() => undefined);
    throw new Error("Download interrupted. Check your connection and retry.");
  } finally {
    reader.releaseLock();
  }
  if (total !== null && loaded !== total) throw new Error("The download was incomplete. Retry.");
  onProgress({ loaded, total });
  const objectUrl = URL.createObjectURL(new Blob(chunks, { type: expectedContentType }));
  try {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filenameFromDisposition(response.headers.get("Content-Disposition"), fallbackName);
    anchor.rel = "noreferrer";
    document.body.appendChild(anchor);
    try {
      anchor.click();
    } finally {
      anchor.remove();
    }
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  }
}

export async function downloadDriveFile(
  fileId: number,
  fallbackName: string,
  onProgress: (progress: DownloadProgress) => void,
): Promise<FileDownloadResult> {
  const authorization = await requestAccountApi<
    { mode: "backend" } | { mode: "presigned"; url: string; filename: string; expires_in: number; size_bytes: number }
  >(`/drive/files/${fileId}/download-url/`, { cache: "no-store", redirect: "error", referrerPolicy: "no-referrer" });
  if (authorization.mode === "presigned") {
    let url: URL;
    try {
      url = new URL(authorization.url);
      if (
        !["http:", "https:"].includes(url.protocol) || url.username || url.password || url.hash
        || (window.location.protocol === "https:" && url.protocol !== "https:")
        || url.hostname === window.location.hostname || url.hostname === new URL(driveApiBase()).hostname
      ) throw new Error();
    } catch {
      throw new Error("The download service returned an invalid authorization. Retry later.");
    }
    // Không đưa link vào DOM/analytics; tên và byte do response attachment của kho quyết định.
    const anchor = document.createElement("a");
    anchor.href = url.href;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    anchor.referrerPolicy = "no-referrer";
    anchor.click();
    return "browser-started";
  }
  if (authorization.mode !== "backend") throw new Error("The download service returned an unexpected response.");
  await downloadDriveBinary(
    `/drive/files/${fileId}/download/`, fallbackName, "application/octet-stream", onProgress,
  );
  return "received";
}

export function downloadDriveFolder(
  folderId: number,
  folderName: string,
  onProgress: (progress: DownloadProgress) => void,
): Promise<void> {
  if (!Number.isSafeInteger(folderId) || folderId <= 0) {
    return Promise.reject(new Error("Invalid folder ID."));
  }
  return downloadDriveBinary(
    `/drive/folder/${folderId}/download/`, `${folderName}.zip`, "application/zip", onProgress,
  );
}

type DriveApiItem = {
  id: number;
  folderId?: number;
  name: string;
  owner: string;
  ownerInitials: string;
  modified: string;
  size: number | null;
  type: "folder" | "document" | "image";
  starred?: boolean;
  canManage?: boolean;
};

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; value >= 1024 && index < units.length; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${unit}`;
}

export type DriveItem = Omit<DriveApiItem, "size" | "modified"> & {
  size: string;
  modified: string;
  modifiedAt?: string;
};

export type DriveListView = "drive" | "recent" | "trash" | "shared" | "starred";

export type DriveFolderAncestor = {
  id: number;
  name: string;
};

export type DriveFolderDetails = {
  type: "folder";
  name: string;
  owner: string;
  created_at: string;
  modified_at: string;
  location: string;
  ancestors: DriveFolderAncestor[];
  folder_count: number;
  file_count: number;
  access: string;
  permission?: "viewer" | "editor" | null;
  shared_by: string | null;
  last_action: string;
};

export async function getDriveItems(
  folderId: number | null,
  view: DriveListView | "timeline" = "drive",
  searchQuery = "",
  workspaceId?: string | null,
): Promise<DriveItem[]> {
  const params = new URLSearchParams({ view });
  const query = searchQuery.trim().slice(0, 255);
  if (query && view === "drive") params.set("q", query);
  else if (folderId !== null) params.set("folder", String(folderId));
  const result = await requestAccountApi<{ items: DriveApiItem[] }>(`/drive/api/items/?${params.toString()}`, { workspaceId });
  return result.items.map((item) => ({
    ...item,
    size: formatBytes(item.size),
    starred: Boolean(item.starred),
    modifiedAt: item.modified,
    modified: new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(item.modified)),
  }));
}


export async function getDriveFolderDetails(
  folderId: number,
): Promise<DriveFolderDetails> {
  if (!Number.isSafeInteger(folderId) || folderId <= 0) {
    throw new Error("Invalid folder ID.");
  }

  return requestAccountApi<DriveFolderDetails>(
    `/drive/folder/${folderId}/details/`,
  );
}
