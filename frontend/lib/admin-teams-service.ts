import { requestAccountApi } from "@/lib/account-service";
import { buildAdminTeamQuery, type AdminTeamScope, type AdminTeamSort, type RoleCounts } from "@/lib/admin-teams-query";

export type AdminTeam = {
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

export type AdminTeamPage = {
  count: number;
  page: number;
  page_size: number;
  scope: AdminTeamScope;
  sort: AdminTeamSort;
  results: AdminTeam[];
};

/** Reuses the existing platform workspace directory. No new Teams API or model. */
export function getAdminTeams(options: {
  query: string;
  scope: AdminTeamScope;
  sort: AdminTeamSort;
  page: number;
}, signal?: AbortSignal): Promise<AdminTeamPage> {
  return requestAccountApi<AdminTeamPage>(
    `/accounts/api/admin/workspaces/?${buildAdminTeamQuery(options)}`,
    { signal, cache: "no-store" },
  );
}
