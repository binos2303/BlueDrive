/** Shared, deterministic query encoding for the platform user directory. */
export type AdminUserSort = "recent_signin" | "oldest_signin" | "newest" | "oldest" | "name_asc" | "name_desc";
export type AdminUserScope = "users" | "admins";
export type AdminUserStatus = "all" | "active" | "inactive";

export function buildAdminUserQuery(options: {
  scope: AdminUserScope;
  status: AdminUserStatus;
  sort: AdminUserSort;
  query: string;
  page: number;
}): string {
  const page = Number.isSafeInteger(options.page) && options.page > 0 ? options.page : 1;
  return new URLSearchParams({
    scope: options.scope,
    status: options.status,
    sort: options.sort,
    q: options.query.trim().slice(0, 100),
    page: String(page),
  }).toString();
}
