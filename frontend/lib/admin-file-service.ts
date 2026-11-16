import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import type { AdminFileAction, AdminFileLifecycle } from "@/lib/admin-file-policy";
import { buildAdminFileQuery } from "@/lib/admin-file-query";
export { buildAdminFileQuery } from "@/lib/admin-file-query";

export type AdminFileScope = "all" | "my_drive" | "workspace" | "organization";
export type AdminFileStatus = AdminFileLifecycle | "all";
export type AdminFileSort = "newest" | "updated" | "name" | "largest" | "oldest";

export type AdminFile = {
  id: number;
  name: string;
  size_bytes: number;
  mime_type: string;
  owner: { id: number; username: string };
  scope: "my_drive" | "workspace" | "organization";
  organization: { id: string; name: string } | null;
  workspace: { id: string; name: string };
  folder: { id: number; name: string } | null;
  lifecycle: AdminFileLifecycle;
  version_state: string | null;
  current_version: number | null;
  version_count: number | null;
  is_encrypted: boolean;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};

export type AdminFileVersion = {
  id: string;
  number: number;
  state: string;
  is_current: boolean;
  size_bytes: number;
  mime_type: string;
  created_at: string;
  verified_at: string | null;
  storage: { provider: string; state: string; verified_at: string | null }[];
};

export type AdminFileDetail = AdminFile & {
  last_accessed_at: string | null;
  purge_after: string | null;
  versions: AdminFileVersion[];
  versions_limit: number;
};

export type AdminFileDirectoryPage = {
  count: number;
  page: number;
  page_size: number;
  summary: { active: number; trash: number; active_metadata_bytes: number };
  permissions: { can_manage_files: boolean };
  results: AdminFile[];
};

export function getAdminFiles(
  options: Parameters<typeof buildAdminFileQuery>[0], signal?: AbortSignal,
): Promise<AdminFileDirectoryPage> {
  return requestAccountApi<AdminFileDirectoryPage>(`/accounts/api/admin/files/?${buildAdminFileQuery(options)}`, {
    signal, cache: "no-store",
  });
}

export function getAdminFileDetail(fileId: number, signal?: AbortSignal): Promise<AdminFileDetail> {
  if (!Number.isSafeInteger(fileId) || fileId <= 0) return Promise.reject(new Error("Invalid file ID."));
  return requestAccountApi<AdminFileDetail>(`/accounts/api/admin/files/${fileId}/`, { signal, cache: "no-store" });
}

export async function manageAdminFile(input: {
  fileId: number;
  action: AdminFileAction;
  reason: string;
  confirmation?: string;
}): Promise<{ id: number; lifecycle: AdminFileLifecycle | "purged" }> {
  if (!Number.isSafeInteger(input.fileId) || input.fileId <= 0) throw new Error("Invalid file ID.");
  const body: Record<string, string> = { action: input.action, reason: input.reason.trim() };
  if (input.action === "purge") body.confirm_name = input.confirmation ?? "";
  return requestAccountApi<{ id: number; lifecycle: AdminFileLifecycle | "purged" }>(`/accounts/api/admin/files/${input.fileId}/actions/`, {
    method: "POST",
    headers: await accountCsrfHeaders(),
    body: JSON.stringify(body),
  });
}
