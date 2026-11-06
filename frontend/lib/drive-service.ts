import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import { getActiveWorkspaceIdForRequest } from "@/lib/workspace-context";
import { isPreviewSupported, normalizePreviewMimeType } from "@/lib/file-preview-policy";
import { isExpectedDownloadMimeType } from "@/lib/drive-download-policy";

export type DownloadProgress = { loaded: number; total: number | null };

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

/** Fetch private file content using a session; never expose a MinIO URL. */
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

/** One private binary transport for file downloads and folder ZIP archives. */
function downloadDriveBinary(
  path: string,
  fallbackName: string,
  expectedContentType: string,
  onProgress: (progress: DownloadProgress) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("GET", `${driveApiBase()}${path}`);
    xhr.withCredentials = true;
    xhr.responseType = "blob";
    xhr.setRequestHeader("Accept", `${expectedContentType}, application/json`);
    const workspaceId = getActiveWorkspaceIdForRequest();
    if (workspaceId) xhr.setRequestHeader("X-Workspace-ID", workspaceId);
    xhr.onprogress = (event) => onProgress({
      loaded: event.loaded,
      total: event.lengthComputable && event.total > 0 ? event.total : null,
    });
    xhr.onerror = () => reject(new Error("Network error while downloading. Retry the download."));
    xhr.onabort = () => reject(new Error("Download canceled."));
    xhr.onload = async () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        let detail = `Download failed (HTTP ${xhr.status}).`;
        try {
          const body = JSON.parse(await (xhr.response as Blob).text()) as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch {
          // Keep the status-only message for non-JSON responses.
        }
        reject(new Error(detail));
        return;
      }
      if (!isExpectedDownloadMimeType(xhr.getResponseHeader("Content-Type"), expectedContentType)) {
        reject(new Error("The service returned an unexpected response. No file was saved."));
        return;
      }
      try {
        const objectUrl = URL.createObjectURL(xhr.response as Blob);
        const anchor = document.createElement("a");
        anchor.href = objectUrl;
        anchor.download = filenameFromDisposition(
          xhr.getResponseHeader("Content-Disposition"), fallbackName,
        );
        anchor.rel = "noreferrer";
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
        resolve();
      } catch {
        reject(new Error("The file was received but the browser could not save it."));
      }
    };
    try {
      xhr.send();
    } catch {
      reject(new Error("Could not start the download. Retry."));
    }
  });
}

export function downloadDriveFile(
  fileId: number,
  fallbackName: string,
  onProgress: (progress: DownloadProgress) => void,
): Promise<void> {
  return downloadDriveBinary(
    `/drive/files/${fileId}/download/`, fallbackName, "application/octet-stream", onProgress,
  );
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
  shared_by: string | null;
  last_action: string;
};

export async function getDriveItems(
  folderId: number | null,
  view: DriveListView = "drive",
  searchQuery = "",
): Promise<DriveItem[]> {
  const params = new URLSearchParams({ view });
  const query = searchQuery.trim().slice(0, 255);
  if (query && view === "drive") params.set("q", query);
  else if (folderId !== null) params.set("folder", String(folderId));
  const result = await requestAccountApi<{ items: DriveApiItem[] }>(`/drive/api/items/?${params.toString()}`);
  return result.items.map((item) => ({
    ...item,
    size: formatBytes(item.size),
    starred: Boolean(item.starred),
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