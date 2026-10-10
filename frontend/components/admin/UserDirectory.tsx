"use client";

import { useMemo, useState } from "react";
import { Search, ChevronLeft, ChevronRight, Eye, ShieldCheck, UserX, UserCheck, Trash2, X } from "lucide-react";

type UserStatus = "Active" | "Suspended";
type UserRole = "Administrator" | "Infrastructure Manager" | "Team Leader" | "Member" | "Auditor";
type UserRecord = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  team: string;
  status: UserStatus;
  lastActive: string;
  storage: string;
};
type ModalState =
  | { kind: "details"; userId: string }
  | { kind: "role"; userId: string }
  | { kind: "lifecycle"; userId: string; action: "suspend" | "reactivate" | "delete" }
  | null;

const initialUsers: UserRecord[] = [
  { id: "BD-10021", name: "Olivia Martin", email: "olivia.martin@example.com", role: "Administrator", team: "Platform", status: "Active", lastActive: "Today, 10:42 AM", storage: "8.4 GB" },
  { id: "BD-10022", name: "Ethan Wilson", email: "ethan.wilson@example.com", role: "Team Leader", team: "Design", status: "Active", lastActive: "Today, 10:38 AM", storage: "4.2 GB" },
  { id: "BD-10023", name: "Ava Thompson", email: "ava.thompson@example.com", role: "Member", team: "Product", status: "Active", lastActive: "Today, 9:54 AM", storage: "2.1 GB" },
  { id: "BD-10024", name: "Noah Davis", email: "noah.davis@example.com", role: "Member", team: "Platform", status: "Suspended", lastActive: "Oct 08, 2026", storage: "640 MB" },
  { id: "BD-10025", name: "Mia Chen", email: "mia.chen@example.com", role: "Auditor", team: "Security", status: "Active", lastActive: "Yesterday", storage: "1.3 GB" },
  { id: "BD-10026", name: "Jamie Lee", email: "jamie.lee@example.com", role: "Team Leader", team: "Product", status: "Active", lastActive: "Oct 09, 2026", storage: "5.7 GB" },
  { id: "BD-10027", name: "Taylor Kim", email: "taylor.kim@example.com", role: "Member", team: "Design", status: "Active", lastActive: "Oct 07, 2026", storage: "920 MB" },
  { id: "BD-10028", name: "Alex Morgan", email: "alex.morgan@example.com", role: "Member", team: "Security", status: "Active", lastActive: "Oct 06, 2026", storage: "3.6 GB" },
  { id: "BD-10029", name: "Jordan Blake", email: "jordan.blake@example.com", role: "Member", team: "Platform", status: "Active", lastActive: "Oct 05, 2026", storage: "1.8 GB" },
  { id: "BD-10030", name: "Morgan Chen", email: "morgan.chen@example.com", role: "Infrastructure Manager", team: "Platform", status: "Active", lastActive: "Oct 04, 2026", storage: "2.7 GB" },
];
const roles: UserRole[] = ["Administrator", "Infrastructure Manager", "Team Leader", "Member", "Auditor"];
const rolePermissions: Record<UserRole, string[]> = {
  Administrator: ["Manage users and team membership", "Assign approved workspace roles", "Review user activity"],
  "Infrastructure Manager": ["View infrastructure health", "Manage infrastructure configuration and alerts", "No user, team, or role administration"],
  "Team Leader": ["Manage assigned team members", "Manage team file access", "View assigned team activity"],
  Member: ["Manage own files", "Share files when allowed", "View assigned shared folders"],
  Auditor: ["View audit logs", "View role assignments", "Export approved reports"],
};
const pageSize = 5;

export default function UserDirectory() {
  const [users, setUsers] = useState(initialUsers);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("All roles");
  const [teamFilter, setTeamFilter] = useState("All teams");
  const [statusFilter, setStatusFilter] = useState("All statuses");
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState<ModalState>(null);
  const [roleDraft, setRoleDraft] = useState<UserRole>("Member");
  const [notice, setNotice] = useState("");

  const filteredUsers = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return users.filter((user) => {
      const matchesQuery = !normalizedQuery || [user.name, user.email, user.id].some((value) => value.toLowerCase().includes(normalizedQuery));
      const matchesRole = roleFilter === "All roles" || user.role === roleFilter;
      const matchesTeam = teamFilter === "All teams" || user.team === teamFilter;
      const matchesStatus = statusFilter === "All statuses" || user.status === statusFilter;
      return matchesQuery && matchesRole && matchesTeam && matchesStatus;
    });
  }, [users, query, roleFilter, teamFilter, statusFilter]);
  const pageCount = Math.max(1, Math.ceil(filteredUsers.length / pageSize));
  const pageUsers = filteredUsers.slice((page - 1) * pageSize, page * pageSize);
  const activeUser = modal ? users.find((user) => user.id === modal.userId) ?? null : null;

  function updateFilter<T extends string>(setter: (value: T) => void, value: T) {
    setter(value);
    setPage(1);
  }

  function confirmAction() {
    if (!modal || !activeUser) return;
    if (modal.kind === "role") {
      setUsers((current) => current.map((user) => user.id === activeUser.id ? { ...user, role: roleDraft } : user));
      setNotice("Role updated");
    } else if (modal.kind === "lifecycle" && modal.action === "delete") {
      setUsers((current) => current.filter((user) => user.id !== activeUser.id));
      setPage((current) => Math.max(1, Math.min(current, Math.ceil((filteredUsers.length - 1) / pageSize))));
      setNotice("User removed");
    } else if (modal.kind === "lifecycle") {
      const status: UserStatus = modal.action === "suspend" ? "Suspended" : "Active";
      setUsers((current) => current.map((user) => user.id === activeUser.id ? { ...user, status } : user));
      setNotice(`Status updated to ${status}`);
    }
    setModal(null);
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">User Directory</h2>
        </div>
        <span className="rounded-xl border border-border bg-surface px-3 py-2 text-sm text-muted">{users.length} users</span>
      </div>

      {notice && (
        <div role="status" className="mb-4 flex items-start justify-between gap-3 rounded-xl border border-brand/20 bg-brand-soft px-4 py-3 text-sm text-brand-hover">
          <span>{notice}</span>
          <button type="button" aria-label="Dismiss message" onClick={() => setNotice("")}><X size={16} /></button>
        </div>
      )}

      <section className="overflow-hidden rounded-[22px] border border-border bg-surface">
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-4">
          <label className="flex min-w-[220px] flex-1 items-center gap-2 rounded-xl border border-border bg-background px-3">
            <Search size={16} className="text-muted" />
            <input
              value={query}
              onChange={(event) => updateFilter(setQuery, event.target.value)}
              placeholder="Search name, email, or account ID"
              className="h-10 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
            />
          </label>
          <select aria-label="Filter by role" value={roleFilter} onChange={(event) => updateFilter(setRoleFilter, event.target.value)} className="h-10 rounded-xl border border-border bg-surface px-3 text-sm text-foreground">
            <option>All roles</option>
            {roles.map((role) => <option key={role}>{role}</option>)}
          </select>
          <select aria-label="Filter by team" value={teamFilter} onChange={(event) => updateFilter(setTeamFilter, event.target.value)} className="h-10 rounded-xl border border-border bg-surface px-3 text-sm text-foreground">
            <option>All teams</option>
            {[...new Set(initialUsers.map((user) => user.team))].map((team) => <option key={team}>{team}</option>)}
          </select>
          <select aria-label="Filter by status" value={statusFilter} onChange={(event) => updateFilter(setStatusFilter, event.target.value)} className="h-10 rounded-xl border border-border bg-surface px-3 text-sm text-foreground">
            <option>All statuses</option>
            <option>Active</option>
            <option>Suspended</option>
          </select>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-left">
            <thead>
              <tr className="bg-background text-[11px] font-semibold tracking-wide text-muted">
                <th className="px-5 py-3">USER</th><th className="px-4 py-3">ACCOUNT ID</th><th className="px-4 py-3">ROLE</th><th className="px-4 py-3">TEAM</th><th className="px-4 py-3">STATUS</th><th className="px-4 py-3">LAST ACTIVE</th><th className="px-4 py-3">ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              {pageUsers.map((user) => (
                <tr key={user.id} className="border-t border-border/70 transition hover:bg-background">
                  <td className="px-5 py-3.5">
                    <p className="text-sm font-medium text-foreground">{user.name}</p>
                    <p className="mt-0.5 text-xs text-muted">{user.email}</p>
                  </td>
                  <td className="px-4 py-3.5 text-xs text-muted">{user.id}</td>
                  <td className="px-4 py-3.5 text-sm">{user.role}</td>
                  <td className="px-4 py-3.5 text-sm">{user.team}</td>
                  <td className="px-4 py-3.5"><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${user.status === "Active" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>{user.status}</span></td>
                  <td className="px-4 py-3.5 text-xs text-muted">{user.lastActive}</td>
                  <td className="px-4 py-3.5">
                    <div className="flex items-center gap-1">
                      <button type="button" title="View details" aria-label={`View ${user.name} details`} onClick={() => setModal({ kind: "details", userId: user.id })} className="rounded-lg p-2 text-muted hover:bg-brand-soft hover:text-brand"><Eye size={15} /></button>
                      <button type="button" title="Change role" aria-label={`Change ${user.name} role`} onClick={() => { setRoleDraft(user.role); setModal({ kind: "role", userId: user.id }); }} className="rounded-lg p-2 text-muted hover:bg-brand-soft hover:text-brand"><ShieldCheck size={15} /></button>
                      {user.status === "Active"
                        ? <button type="button" title="Suspend" aria-label={`Suspend ${user.name}`} onClick={() => setModal({ kind: "lifecycle", userId: user.id, action: "suspend" })} className="rounded-lg p-2 text-muted hover:bg-amber-50 hover:text-amber-700"><UserX size={15} /></button>
                        : <button type="button" title="Reactivate" aria-label={`Reactivate ${user.name}`} onClick={() => setModal({ kind: "lifecycle", userId: user.id, action: "reactivate" })} className="rounded-lg p-2 text-muted hover:bg-emerald-50 hover:text-emerald-700"><UserCheck size={15} /></button>}
                      <button type="button" title="Delete" aria-label={`Delete ${user.name}`} onClick={() => setModal({ kind: "lifecycle", userId: user.id, action: "delete" })} className="rounded-lg p-2 text-muted hover:bg-rose-50 hover:text-rose-700"><Trash2 size={15} /></button>
                    </div>
                  </td>
                </tr>
              ))}
              {pageUsers.length === 0 && <tr><td colSpan={7} className="px-5 py-12 text-center text-sm text-muted">No users match the selected filters.</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3 text-xs text-muted">
          <span>{filteredUsers.length === 0 ? "0 users" : `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, filteredUsers.length)} of ${filteredUsers.length} users`}</span>
          <div className="flex items-center gap-2">
            <button type="button" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} className="rounded-lg border border-border p-1.5 disabled:opacity-40"><ChevronLeft size={16} /></button>
            <span>Page {page} of {pageCount}</span>
            <button type="button" disabled={page >= pageCount} onClick={() => setPage((current) => Math.min(pageCount, current + 1))} className="rounded-lg border border-border p-1.5 disabled:opacity-40"><ChevronRight size={16} /></button>
          </div>
        </div>
      </section>

      {modal && activeUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/35 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) setModal(null); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="user-modal-title" className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-[22px] border border-border bg-surface p-6 shadow-xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 id="user-modal-title" className="text-lg font-semibold">
                  {modal.kind === "details" ? "User details" : modal.kind === "role" ? "Preview role change" : `${modal.action[0].toUpperCase()}${modal.action.slice(1)} account`}
                </h3>
                <p className="mt-1 text-sm text-muted">{activeUser.name} · {activeUser.id}</p>
              </div>
              <button type="button" onClick={() => setModal(null)} aria-label="Close dialog" className="rounded-lg p-2 text-muted hover:bg-background"><X size={18} /></button>
            </div>

            {modal.kind === "details" ? (
              <div className="mt-5 space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <Detail label="Email" value={activeUser.email} />
                  <Detail label="Status" value={activeUser.status} />
                  <Detail label="Role" value={activeUser.role} />
                  <Detail label="Team" value={activeUser.team} />
                  <Detail label="Last active" value={activeUser.lastActive} />
                  <Detail label="Storage used" value={activeUser.storage} />
                </div>
                <div className="rounded-xl border border-border p-4">
                  <p className="text-sm font-semibold">Recent activity & account history</p>
                  <p className="mt-2 text-sm text-muted">No records</p>
                </div>
                <div className="rounded-xl border border-border p-4">
                  <p className="text-sm font-semibold">Role permission preview</p>
                  <ul className="mt-2 list-inside list-disc space-y-1 text-xs text-foreground/80">
                    {rolePermissions[activeUser.role].map((permission) => <li key={permission}>{permission}</li>)}
                  </ul>
                </div>
              </div>
            ) : modal.kind === "role" ? (
              <div className="mt-5 space-y-4">
                <label className="block text-sm font-medium">New role
                  <select value={roleDraft} onChange={(event) => setRoleDraft(event.target.value as UserRole)} className="mt-2 h-11 w-full rounded-xl border border-border bg-surface px-3 text-sm">
                    {roles.map((role) => <option key={role}>{role}</option>)}
                  </select>
                </label>
                <div className="rounded-xl border border-border bg-background p-4 text-sm">
                  <p>Current role: <strong>{activeUser.role}</strong></p>
                  <p className="mt-1">New role: <strong>{roleDraft}</strong></p>
                </div>
              </div>
            ) : (
              <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                {modal.action === "suspend" && <p>Suspension blocks sign-in. Active sessions and shared access may be affected.</p>}
                {modal.action === "reactivate" && <p>Sign-in access will be restored.</p>}
                {modal.action === "delete" && <p>Deletion may affect owned files, shared access, and audit history. Permanent deletion is unavailable.</p>}
              </div>
            )}

            {modal.kind !== "details" && (
              <div className="mt-6 flex justify-end gap-2">
                <button type="button" onClick={() => setModal(null)} className="rounded-xl border border-border px-4 py-2.5 text-sm font-medium">Cancel</button>
                <button type="button" onClick={confirmAction} disabled={modal.kind === "role" && roleDraft === activeUser.role} className="rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50">Confirm</button>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl bg-background p-3">
      <p className="text-[11px] text-muted">{label}</p>
      <p className="mt-1 truncate text-sm font-medium text-foreground">{value}</p>
    </div>
  );
}
