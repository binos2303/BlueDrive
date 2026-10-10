import { Download, Search } from "lucide-react";
const rows = [
  ["Olivia Martin", "Signed in", "BlueDrive Web", "10:42:18 AM", "Success"],
  ["Ethan Wilson", "Updated team access", "Design Team", "10:38:04 AM", "Review"],
  ["System Scheduler", "Completed backup", "Daily Backup", "10:15:00 AM", "Success"],
  ["Ava Thompson", "Downloaded file", "Quarterly Report.pdf", "09:54:21 AM", "Success"],
  ["Noah Davis", "Failed sign-in", "BlueDrive Web", "09:41:03 AM", "Blocked"],
  ["Mia Chen", "Created shared folder", "Product Team", "09:32:45 AM", "Success"],
];
export default function ActivityPage() {
  return <><div className="mb-6"><h2 className="text-2xl font-semibold">User activity</h2></div><div className="rounded-[22px] border border-border bg-surface"><div className="flex flex-wrap items-center gap-3 border-b border-border p-5"><div className="flex min-w-[220px] flex-1 items-center gap-2 rounded-xl border border-border bg-background px-3"><Search size={16} className="text-muted"/><input placeholder="Search users or events..." className="h-10 min-w-0 flex-1 bg-transparent text-sm outline-none"/></div><button className="flex items-center gap-2 rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-foreground/80"><Download size={16}/> Export</button></div><div className="overflow-x-auto"><table className="w-full min-w-[700px] text-left"><thead><tr className="bg-background text-[11px] font-semibold tracking-wide text-muted/80"><th className="px-6 py-3">USER / SERVICE</th><th className="px-4 py-3">EVENT</th><th className="px-4 py-3">TIME</th><th className="px-4 py-3">RESULT</th></tr></thead><tbody>{rows.map(([user, action, resource, time, status])=><tr key={user+time} className="border-t border-border/70"><td className="px-6 py-4"><p className="text-sm font-medium">{user}</p><p className="mt-1 text-xs text-muted">{resource}</p></td><td className="px-4 py-4 text-sm text-foreground/80">{action}</td><td className="px-4 py-4 text-xs text-muted">{time}</td><td className="px-4 py-4"><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${status === "Success" ? "bg-emerald-50 text-emerald-700" : status === "Review" ? "bg-amber-50 text-amber-700" : "bg-rose-50 text-rose-700"}`}>{status}</span></td></tr>)}</tbody></table></div></div></>;
}
