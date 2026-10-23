import { FileLock2, Search, ShieldCheck, LockKeyhole, Info } from "lucide-react";

export default function AdminFilesPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><p className="text-xs font-medium text-muted">Management / Files</p><h1 className="mt-1 text-2xl font-semibold text-foreground">File Management</h1><p className="mt-2 text-sm text-muted">Review file metadata and security restrictions across BlueDrive.</p></div>
        <span className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-muted">Read-only until admin API is connected</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {[{label:"Total files",icon:FileLock2},{label:"Restricted files",icon:LockKeyhole},{label:"Quarantined files",icon:ShieldCheck}].map(({label,icon:Icon})=><div key={label} className="rounded-2xl border border-border bg-surface p-5"><Icon size={19} className="text-brand-contrast"/><p className="mt-4 text-sm text-muted">{label}</p><p className="mt-1 text-2xl font-semibold text-foreground">—</p></div>)}
      </div>
      <section className="overflow-hidden rounded-2xl border border-border bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4 sm:p-5"><h2 className="font-semibold text-foreground">Files</h2><div className="flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-2 text-sm text-muted"><Search size={16}/><span>Search and filters available after API integration</span></div></div>
        <div className="grid grid-cols-5 gap-3 border-b border-border px-5 py-3 text-xs font-semibold text-muted"><span className="col-span-2">File</span><span>Owner</span><span>Location</span><span>Status</span></div>
        <div className="flex min-h-52 flex-col items-center justify-center gap-3 px-6 py-12 text-center"><Info size={24} className="text-muted"/><h3 className="font-medium text-foreground">File inventory is not connected</h3><p className="max-w-lg text-sm text-muted">Connect an authorized admin file metadata endpoint before showing records. Restrict and quarantine actions must be enforced by Django, not only by the interface.</p></div>
      </section>
    </div>
  );
}
