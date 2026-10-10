const teams = [
  { name: "Platform", lead: "Olivia Martin", members: 12, status: "Active" },
  { name: "Design", lead: "Ethan Wilson", members: 8, status: "Active" },
  { name: "Product", lead: "Jamie Lee", members: 14, status: "Active" },
  { name: "Security", lead: "Mia Chen", members: 5, status: "Active" },
];

export default function TeamsPage() {
  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-2xl font-semibold tracking-tight">Team Management</h2>
        </div>
        <button type="button" disabled className="rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white opacity-60">Create team</button>
      </div>
      <section className="overflow-hidden rounded-[22px] border border-border bg-surface">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[600px] text-left">
            <thead className="bg-background text-[11px] font-semibold tracking-wide text-muted">
              <tr><th className="px-5 py-3">TEAM</th><th className="px-4 py-3">TEAM LEAD</th><th className="px-4 py-3">MEMBERS</th><th className="px-4 py-3">STATUS</th></tr>
            </thead>
            <tbody>{teams.map((team) => (
              <tr key={team.name} className="border-t border-border/70">
                <td className="px-5 py-4 text-sm font-medium">{team.name}</td>
                <td className="px-4 py-4 text-sm">{team.lead}</td>
                <td className="px-4 py-4 text-sm text-muted">{team.members}</td>
                <td className="px-4 py-4"><span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">{team.status}</span></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
