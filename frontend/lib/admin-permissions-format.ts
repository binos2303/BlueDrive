/** Display real server counts; do not present role assignments as unique users. */
export function formatAdminRoleCount(
  count: number,
  unit: "accounts" | "assignments",
): string {
  const safeCount = Number.isSafeInteger(count) && count >= 0 ? count : 0;
  const singular = unit === "accounts" ? "account" : "assignment";
  return `${safeCount.toLocaleString("en-US")} active ${singular}${safeCount === 1 ? "" : "s"}`;
}
