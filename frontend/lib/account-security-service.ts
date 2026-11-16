import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";

const BASE = "/accounts/api/me/security";

export type AccountSession = {
  id: string;
  current: boolean;
  startedAt: string;
  lastSeenAt: string;
  expiresAt: string;
  userAgent: string;
};

export type AccountSessionsPage = {
  count: number;
  page: number;
  pageSize: number;
  note: string;
  sessions: AccountSession[];
};

export function getAccountSessions(page: number): Promise<AccountSessionsPage> {
  return requestAccountApi<AccountSessionsPage>(`${BASE}/sessions/?page=${page}`);
}

export async function changeAccountPassword(values: {
  old_password: string;
  new_password1: string;
  new_password2: string;
}) {
  return requestAccountApi<{ changed: boolean; otherSessionsRevoked: number }>(`${BASE}/password/`, {
    method: "POST", headers: await accountCsrfHeaders(), body: JSON.stringify(values),
  });
}

export async function revokeAccountSession(sessionId: string, currentPassword: string) {
  return requestAccountApi<{ revoked: boolean; signedOut: boolean }>(
    `${BASE}/sessions/${encodeURIComponent(sessionId)}/`, {
      method: "DELETE", headers: await accountCsrfHeaders(),
      body: JSON.stringify({ current_password: currentPassword }),
    },
  );
}

export async function revokeOtherAccountSessions(currentPassword: string) {
  return requestAccountApi<{ revoked: number }>(`${BASE}/sessions/revoke-others/`, {
    method: "POST", headers: await accountCsrfHeaders(),
    body: JSON.stringify({ current_password: currentPassword }),
  });
}
