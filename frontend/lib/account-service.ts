import { getActiveWorkspaceIdForRequest } from "@/lib/workspace-context";

export type AccountType = "individual" | "business" | "unclassified";

export type AccountSnapshot = {
  profile: {
    username: string;
    email: string;
  };
  account: {
    type: AccountType;
    tenant: { id: string; name: string; role: string } | null;
    upgradeEligible: boolean | null;
  };
  memberships: Array<{
    id: string;
    name: string;
    type: "personal" | "business";
    role: string;
  }>;
};

export type ProfileUpdate = Pick<AccountSnapshot["profile"], "email">;

export interface AccountService {
  getCurrentAccount(): Promise<AccountSnapshot>;
  updateProfile(input: ProfileUpdate): Promise<AccountSnapshot>;
  signOut(): Promise<void>;
  requestUpgrade(): Promise<void>;
}

export class AccountServiceError extends Error {
  constructor(
    message: string,
    readonly status: number | null = null,
    readonly fieldErrors: Record<string, string[]> = {},
  ) {
    super(message);
    this.name = "AccountServiceError";
  }
}

function apiBase(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!base) {
    throw new AccountServiceError(
      "Account service is not connected. Configure NEXT_PUBLIC_API_BASE_URL to use backend account features.",
    );
  }
  return base.replace(/\/+$/, "");
}

export async function requestAccountApi<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    const headers = new Headers(init.headers);
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    if (init.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    const requestPath = path.split("?", 1)[0] ?? path;
    const isWorkspaceScopedRequest = /^\/(drive|files|folders|sharing)\//.test(requestPath);
    if (isWorkspaceScopedRequest) {
      // The server remains the authorization boundary; this header only selects
      // the active workspace context for the existing Drive APIs.
      headers.delete("X-Workspace-ID");
      const workspaceId = getActiveWorkspaceIdForRequest();
      if (workspaceId) headers.set("X-Workspace-ID", workspaceId);
    }

    response = await fetch(`${apiBase()}${path}`, {
      ...init,
      credentials: "include",
      headers,
    });
  } catch (error) {
    if (error instanceof AccountServiceError) throw error;
    throw new AccountServiceError("Could not reach the account service. Check your connection and retry.");
  }

  if (!response.ok) {
    let detail: {
      detail?: string;
      fieldErrors?: Record<string, Array<string | { message?: string }>>;
      error?: {
        message?: string;
        field_errors?: Record<string, string[]>;
      };
    } = {};
    try {
      detail = await response.json();
    } catch {
      // Keep an explicit HTTP status when the response has no JSON body.
    }
    const rawFieldErrors = detail.fieldErrors ?? detail.error?.field_errors ?? {};
    const fieldErrors = Object.fromEntries(
      Object.entries(rawFieldErrors).map(([field, errors]) => [
        field,
        errors.map((error) =>
          typeof error === "string" ? error : error.message ?? "Invalid value.",
        ),
      ]),
    );
    throw new AccountServiceError(
      detail.detail ?? detail.error?.message ?? `Account request failed (HTTP ${response.status}).`,
      response.status,
      fieldErrors,
    );
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function accountCsrfHeaders(): Promise<Record<string, string>> {
  const result = await requestAccountApi<{ csrfToken: string }>("/accounts/api/csrf/");
  return { "X-CSRFToken": result.csrfToken };
}

export const djangoAccountService: AccountService = {
  getCurrentAccount() {
    return requestAccountApi<AccountSnapshot>("/accounts/api/me/");
  },
  async updateProfile(input) {
    return requestAccountApi<AccountSnapshot>("/accounts/api/me/", {
      method: "PATCH",
      headers: await accountCsrfHeaders(),
      body: JSON.stringify(input),
    });
  },
  async signOut() {
    await requestAccountApi<void>("/accounts/api/logout/", {
      method: "POST",
      headers: await accountCsrfHeaders(),
    });
  },
  async requestUpgrade() {
    throw new AccountServiceError(
      "Personal plan upgrades are not connected. No plan change was made.",
    );
  },
};

export function getConfiguredSupportUrl(): string | null {
  const raw = process.env.NEXT_PUBLIC_SUPPORT_URL?.trim();
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}
