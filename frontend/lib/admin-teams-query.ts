/** Teams are active collaboration workspaces, not a separate role system. */
export type AdminTeamScope = "all" | "personal" | "organization";
export type AdminTeamSort = "newest" | "oldest" | "name_asc" | "name_desc";

export function buildAdminTeamQuery(options: {
  query: string;
  scope: AdminTeamScope;
  sort: AdminTeamSort;
  page: number;
}): string {
  const page = Number.isSafeInteger(options.page) && options.page > 0 ? Math.min(options.page, 100000) : 1;
  return new URLSearchParams({
    q: options.query.trim().slice(0, 100),
    scope: options.scope,
    sort: options.sort,
    page: String(page),
  }).toString();
}

export type RoleCounts = { admin: number; editor: number; viewer: number };

/** Only explicit, current WorkspaceMembership assignments are counted. */
export function countAssignedMembers(roles: RoleCounts): number {
  return roles.admin + roles.editor + roles.viewer;
}
