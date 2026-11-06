import AdminPageHeader from "@/components/admin/AdminPageHeader";
import { Info } from "lucide-react";

export default function SecurityAlertsPage() {
  return <div className="space-y-6">
    <AdminPageHeader title="Security Alerts" />
    <section className="overflow-hidden rounded-2xl border border-border bg-surface"><div className="border-b border-border p-5"><h2 className="font-semibold text-foreground">Alert queue</h2><p className="mt-1 text-xs text-muted">Severity, status, affected user, evidence and timestamps will appear here.</p></div><div className="flex min-h-56 flex-col items-center justify-center gap-3 px-6 py-12 text-center"><Info size={24} className="text-muted"/><h3 className="font-medium text-foreground">Detection pipeline not connected</h3><p className="max-w-lg text-sm text-muted">No live alert data is available. Configure server-side event collection, detection rules and role-checked alert APIs before enabling acknowledgement or account suspension.</p></div></section>
  </div>;
}
