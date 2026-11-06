import type { AdminFileScope, AdminFileStatus, AdminFileSort } from "./admin-file-service";

/** Allowlist and normalization match the backend file-inventory API. */
export function buildAdminFileQuery(options: {
  query: string;
  scope: AdminFileScope;
  status: AdminFileStatus;
  sort: AdminFileSort;
  page: number;
}): string {
  return new URLSearchParams({
    q: options.query.trim().slice(0, 120),
    scope: options.scope,
    status: options.status,
    type: "all", // Legacy API supports file-type filtering; UI intentionally omits it.
    sort: options.sort,
    page: String(Number.isSafeInteger(options.page) && options.page > 0 ? options.page : 1),
  }).toString();
}
