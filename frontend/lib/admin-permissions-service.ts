import { requestAccountApi } from "@/lib/account-service";

export type AdminPermissionRole = {
  id: string;
  scope: "platform" | "tenant" | "workspace";
  label: string;
  description: string;
  capabilities: string[];
  restriction: string;
  count: number;
  count_unit: "accounts" | "assignments";
};

export type AdminPermissionsResponse = {
  roles: AdminPermissionRole[];
  notes: string[];
};

export function getAdminPermissions(signal?: AbortSignal): Promise<AdminPermissionsResponse> {
  return requestAccountApi<AdminPermissionsResponse>(
    "/accounts/api/admin/permissions/",
    { signal, cache: "no-store" },
  );
}
