import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";

export type ShareTarget = { kind: "file" | "folder"; id: number; name: string };
export type SharePermission = "viewer" | "editor";
export type DirectShare = {
  id: number;
  item: ShareTarget;
  recipient: { username: string; email: string };
  permission: SharePermission;
  created_at: string;
};
export type SharePage = {
  items: DirectShare[];
  page: number;
  page_size: number;
  pages: number;
  total: number;
  item: ShareTarget | null;
  can_manage: boolean | null;
};
export type ShareMutation = { changed: boolean; share: DirectShare; detail: string };

/** Never send arbitrary workspace IDs: the existing API client attaches the active selection. */
export function listDirectShares(page = 1, target?: ShareTarget): Promise<SharePage> {
  const params = new URLSearchParams({ page: String(page), page_size: "20" });
  if (target) {
    params.set("kind", target.kind);
    params.set("id", String(target.id));
  }
  return requestAccountApi<SharePage>(`/drive/api/shares/?${params}`);
}

export async function grantDirectShare(target: ShareTarget, email: string, permission: SharePermission) {
  return requestAccountApi<{ detail: string; count: number }>("/drive/api/items/share/", {
    method: "POST",
    headers: await accountCsrfHeaders(),
    body: JSON.stringify({
      file_ids: target.kind === "file" ? [target.id] : [],
      folder_ids: target.kind === "folder" ? [target.id] : [],
      email, permission,
    }),
  });
}

// A single mutation path is used for role changes and revocation.
export async function updateDirectShare(shareId: number, permission: SharePermission): Promise<ShareMutation> {
  return requestAccountApi<ShareMutation>(`/drive/api/shares/${shareId}/`, {
    method: "PATCH", headers: await accountCsrfHeaders(), body: JSON.stringify({ permission }),
  });
}

export async function revokeDirectShare(shareId: number): Promise<void> {
  await requestAccountApi<{ revoked: boolean }>(`/drive/api/shares/${shareId}/`, {
    method: "DELETE", headers: await accountCsrfHeaders(),
  });
}
