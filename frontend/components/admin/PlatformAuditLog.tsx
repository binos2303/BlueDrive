import AdminLogDirectory from "@/components/admin/AdminLogDirectory";

/** Compatibility wrapper: keep one shared log-table implementation. */
export default function PlatformAuditLog() {
  return <AdminLogDirectory mode="audit" />;
}
