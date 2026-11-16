import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import type { AdminSettingsDraft } from "@/lib/admin-settings-policy";

export type AdminSettingsResponse = {
  display_name: string;
  revision: number;
  updated_at: string | null;
  can_edit: boolean;
  effective_security: {
    session_cookie_age_seconds: number;
    expire_at_browser_close: boolean;
    session_cookie_secure: boolean;
    csrf_cookie_secure: boolean;
    admin_audit: "enforced_for_supported_actions";
    maintenance_mode: "not_configured";
  };
};

export function getAdminSettings(signal?: AbortSignal): Promise<AdminSettingsResponse> {
  return requestAccountApi<AdminSettingsResponse>(
    "/accounts/api/admin/settings/",
    { signal, cache: "no-store" },
  );
}

export async function saveAdminSettings(draft: AdminSettingsDraft): Promise<AdminSettingsResponse> {
  return requestAccountApi<AdminSettingsResponse>("/accounts/api/admin/settings/", {
    method: "PATCH",
    headers: await accountCsrfHeaders(),
    body: JSON.stringify(draft),
  });
}

export const ADMIN_CONSOLE_NAME_UPDATED = "bluedrive:admin-console-name-updated";
