import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import { getActiveWorkspaceIdForRequest } from "@/lib/workspace-context";

export type UserActivityEvent = {
  id: number;
  action: string;
  actionLabel: string;
  description: string;
  tenantName: string | null;
  workspaceId: string | null;
  workspaceName: string | null;
  createdAt: string;
  metadata: Record<string, unknown>;
};

export type SearchHistoryItem = {
  id: number;
  query: string;
  resultCount: number;
  workspaceName: string | null;
  createdAt: string;
};

export type MyQuotaSummary = {
  configured: boolean;
  workspaceId: string;
  workspaceName?: string;
  tenantName: string;
  scope?: "tenant" | "member";
  limitBytes: number | null;
  usedBytes: number | null;
  reservedBytes: number | null;
  remainingBytes: number | null;
  percentUsed: number | null;
  organizationCap?: {
    limitBytes: number | null;
    usedBytes: number;
    reservedBytes: number;
    remainingBytes: number | null;
    percentUsed: number | null;
  };
  message?: string;
  updatedAt?: string;
};

function workspaceHeaders(): Headers {
  const headers = new Headers();
  const workspaceId = getActiveWorkspaceIdForRequest();
  if (workspaceId) headers.set("X-Workspace-ID", workspaceId);
  return headers;
}

export async function getMyQuota(): Promise<MyQuotaSummary> {
  return requestAccountApi<MyQuotaSummary>("/accounts/api/me/quota/", {
    headers: workspaceHeaders(),
  });
}

export async function getMyActivity(limit = 50): Promise<UserActivityEvent[]> {
  const params = new URLSearchParams({ limit: String(Math.max(1, Math.min(100, limit))) });
  const result = await requestAccountApi<{ events: UserActivityEvent[] }>(
    `/accounts/api/me/activity/?${params.toString()}`,
  );
  return result.events;
}

export async function getMySearchHistory(limit = 50): Promise<SearchHistoryItem[]> {
  const params = new URLSearchParams({ limit: String(Math.max(1, Math.min(100, limit))) });
  const result = await requestAccountApi<{ items: SearchHistoryItem[] }>(
    `/accounts/api/me/search-history/?${params.toString()}`,
  );
  return result.items;
}

export async function clearMySearchHistory(): Promise<number> {
  const result = await requestAccountApi<{ deletedCount: number }>(
    "/accounts/api/me/search-history/",
    { method: "DELETE", headers: await accountCsrfHeaders() },
  );
  return result.deletedCount;
}

export async function deleteMyDriveData(input: {
  password: string;
  confirmation: "DELETE MY DRIVE";
}): Promise<{ detail: string; filesDeleted: number; foldersDeleted: number; auditLogRetained: boolean }> {
  return requestAccountApi("/accounts/api/me/delete-data/", {
    method: "POST",
    headers: await accountCsrfHeaders(),
    body: JSON.stringify(input),
  });
}
