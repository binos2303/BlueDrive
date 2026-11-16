import { requestAccountApi } from "@/lib/account-service";

export type UploadOperations = {
  pending_jobs: number;
  processing_jobs: number;
  failed_jobs: number;
  stale_processing_jobs: number;
  verifying_uploads: number;
  scanning_uploads: number;
  oldest_active_job_at: string | null;
};

export type AdminOverview = {
  users: { total: number; active: number; inactive: number; platform_admins: number; recently_seen: number };
  organizations: { total: number; active: number };
  workspaces: { total: number; active: number; organization: number; personal: number };
  files: { total: number; metadata_bytes: number; in_trash: number };
  health: { api: "responding"; database: "responding"; storage: "not_monitored" };
  uploads: UploadOperations;
};

export function getAdminOverview(signal?: AbortSignal): Promise<AdminOverview> {
  return requestAccountApi("/accounts/api/admin/overview/", { signal, cache: "no-store" });
}
