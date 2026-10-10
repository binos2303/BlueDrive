import { History } from "lucide-react";

export default function UserAuditHistoryPage() {
  return (
    <div>
      <div className="mb-5">
        <h2 className="text-2xl font-semibold tracking-tight">User Audit History</h2>
      </div>
      <section className="rounded-[22px] border border-border bg-surface p-10 text-center">
        <History size={24} className="mx-auto text-muted" />
        <p className="mt-3 text-sm font-medium">No records</p>
      </section>
    </div>
  );
}
