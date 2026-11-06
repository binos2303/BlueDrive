import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";

import { buildAdminUserQuery, type AdminUserSort } from "@/lib/admin-user-query";
export type { AdminUserSort, AdminUserScope, AdminUserStatus } from "@/lib/admin-user-query";

export type AdminUser = {
  id: number;
  username: string;
  email: string;
  is_active: boolean;
  is_staff: boolean;
  is_superuser: boolean;
  last_login: string | null;
  recently_online: boolean;
  date_joined: string | null;
  admin_role?: "super_admin" | "platform_admin" | null;
  admin_status?: "invited" | "active" | "disabled" | null;
};

export type AdminUsersPage = {
  count: number;
  page: number;
  page_size: number;
  sort: AdminUserSort;
  results: AdminUser[];
};

export type AdminSession = {
  id: string;
  user_id: number;
  username: string;
  started_at: string;
  last_seen_at: string;
  expires_at: string;
  recently_online: boolean;
  user_agent: string;
  can_revoke: boolean;
};

export type AdminSessionPage = {
  count: number;
  page: number;
  page_size: number;
  tracking_note: string;
  results: AdminSession[];
};

export function getAdminUsers(
  options: Parameters<typeof buildAdminUserQuery>[0],
  signal?: AbortSignal,
): Promise<AdminUsersPage> {
  return requestAccountApi<AdminUsersPage>(
    `/accounts/api/admin/users/?${buildAdminUserQuery(options)}`,
    { signal, cache: "no-store" },
  );
}

export function getAdminUserOverview(signal?: AbortSignal): Promise<{
  users: { total: number; platform_admins: number };
}> {
  return requestAccountApi("/accounts/api/admin/overview/", { signal, cache: "no-store" });
}

export function getAdminUserSessions(
  userId: number,
  page: number,
  signal?: AbortSignal,
): Promise<AdminSessionPage> {
  if (!Number.isSafeInteger(userId) || userId <= 0) {
    return Promise.reject(new Error("Invalid user ID."));
  }
  const query = new URLSearchParams({
    scope: "users", user_id: String(userId), page: String(Math.max(1, page)),
  });
  return requestAccountApi<AdminSessionPage>(`/accounts/api/admin/sessions/?${query}`, {
    signal, cache: "no-store",
  });
}

export async function revokeAdminUserSession(sessionId: string, reason: string): Promise<void> {
  await requestAccountApi(`/accounts/api/admin/sessions/${encodeURIComponent(sessionId)}/revoke/`, {
    method: "POST",
    headers: await accountCsrfHeaders(),
    body: JSON.stringify({ reason: reason.trim() }),
  });
}
