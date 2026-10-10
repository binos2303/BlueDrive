import { Check, LockKeyhole, ShieldCheck, Users } from "lucide-react";
import RoleAssignments from "@/components/admin/RoleAssignments";

const roles = [
  { name: "Super Admin", members: 2, badge: "Critical", tone: "rose", permissions: ["Manage all users, roles, and teams", "Configure platform security", "Manage infrastructure and backup policies"] },
  { name: "Administrator", members: 4, badge: "User administration", tone: "violet", permissions: ["Manage users and team membership", "Assign approved workspace roles", "Review user activity and audit history"] },
  { name: "Infrastructure Manager", members: 3, badge: "Infrastructure scope", tone: "blue", permissions: ["View server, storage, and database health", "Manage infrastructure configuration and alerts", "No user, team, or role administration"] },
  { name: "Team Leader", members: 8, badge: "Team scope", tone: "blue", permissions: ["Manage assigned team membership", "Manage team file access", "View activity for assigned team"] },
  { name: "Member", members: 126, badge: "Standard", tone: "green", permissions: ["Manage own files", "Share files when allowed", "View assigned shared folders"] },
  { name: "Auditor", members: 3, badge: "Read only", tone: "amber", permissions: ["View audit logs", "View role assignments", "Export approved reports"] },
];

export default function PermissionsPage() {
  return (
    <>
      <div className="mb-5">
        <h2 className="text-2xl font-semibold">Roles & Permissions</h2>
      </div>

      <div className="mb-5 grid gap-4 sm:grid-cols-3">
        <Summary label="Defined roles" value="6" icon={ShieldCheck} />
        <Summary label="Assigned users" value="146" icon={Users} />
        <Summary label="Access model" value="RBAC + team scope" icon={LockKeyhole} />
      </div>

      <div className="space-y-4">
        {roles.map((role) => (
          <section key={role.name} className="rounded-[22px] border border-border bg-surface p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="flex items-start gap-3">
                <span className="flex h-11 w-11 items-center justify-center rounded-[14px] bg-brand-soft text-brand"><ShieldCheck size={20} /></span>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold">{role.name}</h3>
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${role.tone === "rose" ? "bg-rose-50 text-rose-700" : role.tone === "violet" ? "bg-violet-50 text-violet-700" : role.tone === "blue" ? "bg-brand-soft text-brand-hover" : role.tone === "green" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>{role.badge}</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 text-sm text-muted"><Users size={16} />{role.members} users</div>
            </div>
            <div className="mt-5 grid gap-2 sm:grid-cols-3">
              {role.permissions.map((permission) => (
                <div key={permission} className="flex items-start gap-2 rounded-xl bg-background p-3 text-xs leading-5 text-foreground/80">
                  <Check size={15} className="mt-0.5 shrink-0 text-emerald-600" />{permission}
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>

      <RoleAssignments />
    </>
  );
}

function Summary({ label, value, icon: Icon }: { label: string; value: string; icon: typeof ShieldCheck }) {
  return (
    <div className="rounded-[18px] border border-border bg-surface p-4">
      <div className="flex items-center gap-2 text-sm text-muted"><Icon size={17} className="text-brand" />{label}</div>
      <p className="mt-3 text-xl font-semibold">{value}</p>
    </div>
  );
}
