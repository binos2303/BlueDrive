"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, ArrowLeft, Database, HardDrive, Pencil, UsersRound, X } from "lucide-react";

type QuotaUser = {
  name: string;
  limit: number;
  used: number;
  changed: string;
};

type QuotaTeam = {
  name: string;
  limit: number;
  used: number;
  members: number;
  changed: string;
};

const initialUsers: QuotaUser[] = [
  { name: "user_a", limit: 10, used: 7.5, changed: "No changes recorded" },
  { name: "user_b", limit: 5, used: 4.8, changed: "No changes recorded" },
  { name: "user_c", limit: 10, used: 10, changed: "No changes recorded" },
];

const initialTeams: QuotaTeam[] = [
  { name: "Team Alpha", limit: 50, used: 32, members: 8, changed: "No changes recorded" },
  { name: "Team Beta", limit: 30, used: 28, members: 5, changed: "No changes recorded" },
];

const sections = [
  { id: "users", label: "User Quotas" },
  { id: "teams", label: "Team Quotas" },
  { id: "capacity", label: "Storage Capacity" },
  { id: "policies", label: "Quota Policies" },
];

export default function QuotaManagement({ section = "overview" }: { section?: string }) {
  const [users, setUsers] = useState(initialUsers);
  const [teams, setTeams] = useState(initialTeams);
  const [selectedUser, setSelectedUser] = useState<QuotaUser | null>(null);
  const [editingQuota, setEditingQuota] = useState<{ name: string; limit: number; used: number; entity: "user" | "team" } | null>(null);

  function saveQuota(limit: number) {
    if (!editingQuota) return;
    const changed = `Preview updated · ${formatGB(editingQuota.limit)} → ${formatGB(limit)}`;
    if (editingQuota.entity === "user") {
      setUsers((current) => current.map((user) => user.name === editingQuota.name ? { ...user, limit, changed } : user));
      setSelectedUser((current) => current?.name === editingQuota.name ? { ...current, limit, changed } : current);
    } else {
      setTeams((current) => current.map((team) => team.name === editingQuota.name ? { ...team, limit, changed } : team));
    }
    setEditingQuota(null);
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {section !== "overview" && <Link href="/admin/infrastructure/quotas" aria-label="Back to quota overview" className="rounded-lg p-2 text-muted hover:bg-background"><ArrowLeft size={18} /></Link>}
          <h2 className="text-2xl font-semibold tracking-tight">{getTitle(section)}</h2>
        </div>
        {section !== "capacity" && <span className="rounded-full bg-brand-soft px-2.5 py-1 text-xs font-medium text-brand">Illustrative data</span>}
      </div>

      <nav aria-label="Quota management sections" className="mb-5 flex gap-2 overflow-x-auto pb-1">
        <SectionLink id="overview" active={section === "overview"}>Overview</SectionLink>
        {sections.map(({ id, label }) => <SectionLink key={id} id={id} active={section === id}>{label}</SectionLink>)}
      </nav>

      {section === "overview" && <Overview users={users} />}
      {section === "users" && <UserQuotas users={users} onSelectUser={setSelectedUser} onEditUser={(user) => setEditingQuota({ ...user, entity: "user" })} />}
      {section === "teams" && <TeamQuotas teams={teams} onEditTeam={(team) => setEditingQuota({ ...team, entity: "team" })} />}
      {section === "capacity" && <StorageCapacity />}
      {section === "policies" && <QuotaPolicies />}
      {selectedUser && <UserDetails user={selectedUser} onClose={() => setSelectedUser(null)} onEdit={() => setEditingQuota({ ...selectedUser, entity: "user" })} />}
      {editingQuota && <QuotaEditor quota={editingQuota} onClose={() => setEditingQuota(null)} onSave={saveQuota} />}
    </div>
  );
}

function getTitle(section: string) {
  if (section === "overview") return "Quota Management";
  return sections.find((item) => item.id === section)?.label ?? "Quota Management";
}

function SectionLink({ id, active, children }: { id: string; active: boolean; children: React.ReactNode }) {
  return (
    <Link href={id === "overview" ? "/admin/infrastructure/quotas" : `/admin/infrastructure/quotas/${id}`} aria-current={active ? "page" : undefined} className={`shrink-0 rounded-xl px-3.5 py-2.5 text-sm font-medium transition ${active ? "bg-brand-soft text-brand" : "bg-surface text-muted hover:bg-background hover:text-foreground"}`}>
      {children}
    </Link>
  );
}

function Overview({ users }: { users: QuotaUser[] }) {
  const used = users.reduce((total, user) => total + user.used, 0);
  const quota = users.reduce((total, user) => total + user.limit, 0);
  const remaining = quota - used;
  const nearLimit = users.filter((user) => user.used / user.limit >= 0.9).length;
  const metrics = [
    { label: "Total quota", value: formatGB(quota), icon: Database },
    { label: "Used", value: formatGB(used), icon: HardDrive },
    { label: "Available", value: formatGB(remaining), icon: HardDrive },
    { label: "Users near quota", value: `${nearLimit}`, icon: UsersRound },
  ];

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map(({ label, value, icon: Icon }) => <Metric key={label} label={label} value={value} icon={Icon} />)}
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <SectionCard href="/admin/infrastructure/quotas/users" title="User Quotas" detail="Review usage and individual limits" icon={UsersRound} />
        <SectionCard href="/admin/infrastructure/quotas/capacity" title="Storage Capacity" detail="Physical disk and object storage" icon={HardDrive} />
      </div>
      <div className="mt-5 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
        <AlertTriangle size={18} className="mt-0.5 shrink-0" />
        <p className="text-sm">Quota values are illustrative. Physical storage capacity is monitored separately.</p>
      </div>
    </>
  );
}

function UserQuotas({ users, onSelectUser, onEditUser }: { users: QuotaUser[]; onSelectUser: (user: QuotaUser) => void; onEditUser: (user: QuotaUser) => void }) {
  return (
    <section className="overflow-hidden rounded-[22px] border border-border bg-surface">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left">
          <thead className="bg-background text-[11px] font-semibold tracking-wide text-muted">
            <tr><th className="px-5 py-3">USER</th><th className="px-4 py-3">QUOTA LIMIT</th><th className="px-4 py-3">USED</th><th className="px-4 py-3">AVAILABLE</th><th className="px-4 py-3">USAGE</th><th className="px-4 py-3">ACTIONS</th></tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const available = Math.max(0, user.limit - user.used);
              const percent = Math.round((user.used / user.limit) * 100);
              return (
                <tr key={user.name} className="border-t border-border/70">
                  <td className="px-5 py-4 text-sm font-semibold">{user.name}</td>
                  <td className="px-4 py-4 text-sm">{formatGB(user.limit)}</td>
                  <td className="px-4 py-4 text-sm">{formatGB(user.used)}</td>
                  <td className="px-4 py-4 text-sm">{formatGB(available)}</td>
                  <td className="px-4 py-4">
                    <div className="flex min-w-32 items-center gap-2"><div className="h-2 flex-1 overflow-hidden rounded-full bg-background"><div className={`h-full rounded-full ${percent >= 90 ? "bg-amber-500" : "bg-brand"}`} style={{ width: `${percent}%` }} /></div><span className="w-10 text-right text-xs font-medium">{percent}%</span></div>
                  </td>
                  <td className="px-4 py-4">
                    <div className="flex items-center gap-1">
                      <button type="button" onClick={() => onSelectUser(user)} className="rounded-lg px-2.5 py-1.5 text-xs font-semibold text-muted hover:bg-background">Details</button>
                      <button type="button" onClick={() => onEditUser(user)} className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-brand hover:bg-brand-soft"><Pencil size={13} />Edit quota</button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TeamQuotas({ teams, onEditTeam }: { teams: QuotaTeam[]; onEditTeam: (team: QuotaTeam) => void }) {
  return (
    <div className="space-y-4">
      <UnavailableNotice>Illustrative team quotas. Confirm shared storage ownership and quota calculation before enabling backend enforcement.</UnavailableNotice>
      <section className="overflow-hidden rounded-[22px] border border-border bg-surface">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-left">
            <thead className="bg-background text-[11px] font-semibold tracking-wide text-muted"><tr><th className="px-5 py-3">TEAM</th><th className="px-4 py-3">QUOTA LIMIT</th><th className="px-4 py-3">USED</th><th className="px-4 py-3">AVAILABLE</th><th className="px-4 py-3">MEMBERS</th><th className="px-4 py-3">ACTIONS</th></tr></thead>
            <tbody>
              {teams.map((team) => (
                <tr key={team.name} className="border-t border-border/70">
                  <td className="px-5 py-4 text-sm font-semibold">{team.name}</td>
                  <td className="px-4 py-4 text-sm">{formatGB(team.limit)}</td>
                  <td className="px-4 py-4 text-sm">{formatGB(team.used)}</td>
                  <td className="px-4 py-4 text-sm">{formatGB(Math.max(0, team.limit - team.used))}</td>
                  <td className="px-4 py-4 text-sm">{team.members}</td>
                  <td className="px-4 py-4"><button type="button" onClick={() => onEditTeam(team)} className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-brand hover:bg-brand-soft"><Pencil size={13} />Edit quota</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function StorageCapacity() {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <Metric label="Physical capacity" value="Unknown" icon={HardDrive} />
        <Metric label="Used capacity" value="Unknown" icon={Database} />
        <Metric label="Available capacity" value="Unknown" icon={HardDrive} />
      </div>
      <UnavailableNotice>Disk and MinIO capacity are separate from user and team quotas.</UnavailableNotice>
      <section className="overflow-hidden rounded-[22px] border border-border bg-surface">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left">
            <thead className="bg-background text-[11px] font-semibold tracking-wide text-muted"><tr><th className="px-5 py-3">STORAGE</th><th className="px-4 py-3">TYPE</th><th className="px-4 py-3">CAPACITY</th><th className="px-4 py-3">STATUS</th></tr></thead>
            <tbody>
              <tr className="border-t border-border/70"><td className="px-5 py-4 text-sm font-medium">Server disk</td><td className="px-4 py-4 text-sm text-muted">Filesystem</td><td className="px-4 py-4 text-sm text-muted">Unknown</td><td className="px-4 py-4"><UnknownBadge /></td></tr>
              <tr className="border-t border-border/70"><td className="px-5 py-4 text-sm font-medium">MinIO</td><td className="px-4 py-4 text-sm text-muted">Object storage</td><td className="px-4 py-4 text-sm text-muted">Unknown</td><td className="px-4 py-4"><UnknownBadge /></td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function QuotaPolicies() {
  return (
    <div className="space-y-4">
      <UnavailableNotice>Policy changes are disabled until the backend supports quota enforcement.</UnavailableNotice>
      <section className="max-w-3xl space-y-5 rounded-[22px] border border-border bg-surface p-5 sm:p-6">
        <ReadOnlyField label="Default user quota" value="Not configured" />
        <ReadOnlyField label="Maximum file upload size" value="Not configured" />
        <ReadOnlyField label="Warning threshold" value="Not configured" />
        <ReadOnlyField label="Quota enforcement" value="Unknown" />
        <div className="flex items-start gap-3 rounded-xl bg-background p-4 text-sm text-muted">
          <AlertTriangle size={17} className="mt-0.5 shrink-0 text-amber-600" />
          Lowering a quota below current usage should block new uploads without deleting existing files.
        </div>
        <button type="button" disabled className="rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white opacity-50">Save policy</button>
      </section>
    </div>
  );
}

function UserDetails({ user, onClose, onEdit }: { user: QuotaUser; onClose: () => void; onEdit: () => void }) {
  const percent = Math.round((user.used / user.limit) * 100);
  const overLimit = user.used > user.limit;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="quota-user-title" className="w-full max-w-lg rounded-[22px] bg-surface p-5 shadow-xl sm:p-6">
        <div className="flex items-center justify-between">
          <h3 id="quota-user-title" className="text-lg font-semibold">{user.name}</h3>
          <button type="button" aria-label="Close user details" onClick={onClose} className="rounded-lg p-2 text-muted hover:bg-background"><X size={18} /></button>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-3">
          <DetailValue label="Quota limit" value={formatGB(user.limit)} />
          <DetailValue label="Used" value={formatGB(user.used)} />
          <DetailValue label="Available" value={formatGB(Math.max(0, user.limit - user.used))} />
          <DetailValue label="Usage" value={`${percent}%`} />
        </div>
        <div className="mt-4 rounded-xl bg-background p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Quota change history</p>
          <p className="mt-2 text-sm">{user.changed}</p>
        </div>
        {overLimit && <p className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">Usage exceeds quota. New uploads should be blocked; existing files remain unchanged.</p>}
        <button type="button" onClick={onEdit} className="mt-5 w-full rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-hover">Edit quota</button>
      </section>
    </div>
  );
}

function QuotaEditor({
  quota,
  onClose,
  onSave,
}: {
  quota: { name: string; limit: number; used: number; entity: "user" | "team" };
  onClose: () => void;
  onSave: (limit: number) => void;
}) {
  const [newLimit, setNewLimit] = useState(String(quota.limit));
  const parsedLimit = Number(newLimit);
  const validLimit = newLimit.trim() !== "" && Number.isFinite(parsedLimit) && parsedLimit > 0;
  const exceedsUsage = validLimit && parsedLimit < quota.used;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/40 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="quota-editor-title"
        className="w-full max-w-md rounded-[22px] bg-surface p-5 shadow-xl sm:p-6"
        onSubmit={(event) => {
          event.preventDefault();
          if (validLimit) onSave(parsedLimit);
        }}
      >
        <div className="flex items-center justify-between">
          <h3 id="quota-editor-title" className="text-lg font-semibold">Edit {quota.entity} quota</h3>
          <button type="button" aria-label="Close quota editor" onClick={onClose} className="rounded-lg p-2 text-muted hover:bg-background"><X size={18} /></button>
        </div>
        <p className="mt-1 text-sm text-muted">{quota.name}</p>
        <label className="mt-5 block text-sm font-medium">
          New quota limit (GB)
          <input autoFocus type="number" min="0.1" step="0.1" required value={newLimit} onChange={(event) => setNewLimit(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-border bg-background px-3 text-sm outline-none focus:border-brand" />
        </label>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <DetailValue label="Current usage" value={formatGB(quota.used)} />
          <DetailValue label="Available after change" value={validLimit ? formatGB(Math.max(0, parsedLimit - quota.used)) : "—"} />
        </div>
        {exceedsUsage && (
          <p className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
            The new limit is below current usage. New uploads should be blocked; existing files will not be deleted.
          </p>
        )}
        <p className="mt-4 rounded-xl bg-background p-3 text-xs text-muted">Preview only — quota changes are not saved to the backend.</p>
        <div className="mt-5 flex gap-3">
          <button type="button" onClick={onClose} className="flex-1 rounded-xl border border-border px-4 py-2.5 text-sm font-semibold text-muted hover:bg-background">Cancel</button>
          <button type="submit" disabled={!validLimit} className="flex-1 rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">Preview change</button>
        </div>
      </form>
    </div>
  );
}

function Metric({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Database }) {
  return (
    <section className="rounded-[20px] border border-border bg-surface p-5">
      <div className="flex items-center justify-between"><p className="text-sm text-muted">{label}</p><span className="rounded-xl bg-brand-soft p-2.5 text-brand"><Icon size={18} /></span></div>
      <p className="mt-4 text-2xl font-semibold">{value}</p>
    </section>
  );
}

function SectionCard({ href, title, detail, icon: Icon }: { href: string; title: string; detail: string; icon: typeof Database }) {
  return (
    <Link href={href} className="flex items-center gap-4 rounded-[20px] border border-border bg-surface p-5 transition hover:bg-background">
      <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand"><Icon size={20} /></span>
      <span className="min-w-0 flex-1"><span className="block text-sm font-semibold">{title}</span><span className="mt-1 block text-xs text-muted">{detail}</span></span>
    </Link>
  );
}

function UnavailableNotice({ children }: { children: React.ReactNode }) {
  return <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-900"><AlertTriangle size={18} className="mt-0.5 shrink-0" /><p className="text-sm">{children}</p></div>;
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return <label className="block text-sm font-medium">{label}<input disabled value={value} readOnly className="mt-2 h-11 w-full rounded-xl border border-border bg-background px-3 text-sm font-normal text-muted disabled:opacity-70" /></label>;
}

function DetailValue({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl bg-background p-3"><p className="text-xs text-muted">{label}</p><p className="mt-1 text-sm font-semibold">{value}</p></div>;
}

function UnknownBadge() {
  return <span className="rounded-full bg-background px-2.5 py-1 text-xs font-medium text-muted">Unknown</span>;
}

function formatGB(value: number) {
  return `${Number.isInteger(value) ? value : value.toFixed(1)} GB`;
}
