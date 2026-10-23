import { ShieldAlert, CheckCircle2, AlertTriangle, Info } from "lucide-react";

export default function SecurityAlertsPage() {
  return <div className="space-y-6">
    <div><p className="text-xs font-medium text-muted">Security / Alerts</p><h1 className="mt-1 text-2xl font-semibold text-foreground">Security Alerts</h1><p className="mt-2 text-sm text-muted">Investigate unusual account and file activity before taking action.</p></div>
    <div className="grid gap-3 sm:grid-cols-3">{[{label:"Open alerts",icon:ShieldAlert},{label:"Under investigation",icon:AlertTriangle},{label:"Resolved",icon:CheckCircle2}].map(({label,icon:Icon})=><div key={label} className="rounded-2xl border border-border bg-surface p-5"><Icon size={19} className="text-brand-contrast"/><p className="mt-4 text-sm text-muted">{label}</p><p className="mt-1 text-2xl font-semibold text-foreground">—</p></div>)}</div>
    <section className="overflow-hidden rounded-2xl border border-border bg-surface"><div className="border-b border-border p-5"><h2 className="font-semibold text-foreground">Alert queue</h2><p className="mt-1 text-xs text-muted">Severity, status, affected user, evidence and timestamps will appear here.</p></div><div className="flex min-h-56 flex-col items-center justify-center gap-3 px-6 py-12 text-center"><Info size={24} className="text-muted"/><h3 className="font-medium text-foreground">Detection pipeline not connected</h3><p className="max-w-lg text-sm text-muted">No live alert data is available. Configure server-side event collection, detection rules and role-checked alert APIs before enabling acknowledgement or account suspension.</p></div></section>
  </div>;
}
