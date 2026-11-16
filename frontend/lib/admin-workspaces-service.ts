import { requestAccountApi } from "@/lib/account-service";
import { buildAdminWorkspaceQuery, type AdminWorkspaceScope, type AdminWorkspaceSort, type RoleCounts } from "@/lib/admin-workspaces-query";

export type AdminWorkspace = {
  id: string;
  name: string;
  status: "active";
  scope: "organization" | "personal";
  organization: string | null;
  created_at: string;
  created_by: string | null;
  member_count: number;
  role_counts: RoleCounts;
};

export type AdminWorkspacePage = {
  count: number;
  page: number;
  page_size: number;
  scope: AdminWorkspaceScope;
  sort: AdminWorkspaceSort;
  results: AdminWorkspace[];
};

/** Read-only metadata; membership changes remain with workspace managers. */
export function getAdminWorkspaces(options: {
  query: string;
  scope: AdminWorkspaceScope;
  sort: AdminWorkspaceSort;
  page: number;
}, signal?: AbortSignal): Promise<AdminWorkspacePage> {
  return requestAccountApi<AdminWorkspacePage>(
    `/accounts/api/admin/workspaces/?${buildAdminWorkspaceQuery(options)}`,
    { signal, cache: "no-store" },
  );
}
