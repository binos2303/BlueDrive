"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, LockKeyhole, RefreshCw, ShieldCheck, Users } from "lucide-react";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import { formatAdminRoleCount } from "@/lib/admin-permissions-format";
import {
  getAdminPermissions,
  type AdminPermissionRole,
  type AdminPermissionsResponse,
} from "@/lib/admin-permissions-service";

const groups: Array<{ id: AdminPermissionRole["scope"]; title: string; note: string }> = [
  { id: "platform", title: "Platform", note: "Platform roles do not automatically grant access to file content." },
  { id: "tenant", title: "Tenant", note: "Each assignment belongs to a particular organization or personal tenant." },
  { id: "workspace", title: "Workspace", note: "These assignments apply to an individual non-default collaboration workspace." },
];

export default function PermissionsPage() {
  const [result, setResult] = useState<AdminPermissionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getAdminPermissions(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setResult(data);
        setLoading(false);
        setError("");
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : "Permission data unavailable.");
        setLoading(false);
      });
    return () => controller.abort();
  }, [revision]);

  function refresh() {
    setLoading(true);
    setError("");
    setRevision((current) => current + 1);
  }

  return (
    <div className="space-y-5">
      <AdminPageHeader
        title="Roles & Permissions"
        actions={
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="inline-flex h-10 items-center gap-2 rounded-xl border border-border bg-surface px-3 text-sm font-medium hover:bg-background disabled:opacity-50"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
        }
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-border bg-surface px-4 py-3">
          <div className="flex items-center gap-2 text-xs text-muted"><ShieldCheck size={16} /> Defined roles</div>
          <p className="mt-1 text-lg font-semibold">{result?.roles.length ?? "—"}</p>
        </div>
        <div className="rounded-xl border border-border bg-surface px-4 py-3">
          <div className="flex items-center gap-2 text-xs text-muted"><Users size={16} /> Role count source</div>
          <p className="mt-1 text-sm font-semibold">PostgreSQL assignments</p>
        </div>
        <div className="rounded-xl border border-border bg-surface px-4 py-3">
          <div className="flex items-center gap-2 text-xs text-muted"><LockKeyhole size={16} /> Access model</div>
          <p className="mt-1 text-sm font-semibold">Platform + Tenant + Workspace</p>
        </div>
      </div>

      {loading && <p role="status" className="rounded-xl border border-border bg-surface p-4 text-sm text-muted">Loading effective role definitions and live counts…</p>}
      {error && <p role="alert" className="rounded-xl border border-danger/30 bg-surface p-4 text-sm text-danger">{error}</p>}

      {!loading && result && (
        <>
          {groups.map((group) => {
            const roles = result.roles.filter((role) => role.scope === group.id);
            return (
              <section key={group.id} className="space-y-3">
                <div>
                  <h2 className="text-base font-semibold">{group.title} roles</h2>
                  <p className="mt-1 text-xs leading-5 text-muted">{group.note}</p>
                </div>
                <div className="grid gap-3 xl:grid-cols-2">
                  {roles.map((role) => (
                    <article key={role.id} className="rounded-[18px] border border-border bg-surface p-5">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-brand-soft text-brand"><ShieldCheck size={18} /></span>
                          <h3 className="text-sm font-semibold">{role.label}</h3>
                        </div>
                        <span className="rounded-lg bg-background px-2.5 py-1 text-xs font-medium text-muted">
                          {formatAdminRoleCount(role.count, role.count_unit)}
                        </span>
                      </div>
                      <p className="mt-3 text-xs leading-5 text-muted">{role.description}</p>
                      <ul className="mt-3 space-y-2">
                        {role.capabilities.map((capability) => (
                          <li key={capability} className="flex items-start gap-2 text-xs leading-5">
                            <Check size={15} className="mt-0.5 shrink-0 text-success" /> {capability}
                          </li>
                        ))}
                      </ul>
                      <p className="mt-3 border-t border-border pt-3 text-xs leading-5 text-muted">
                        <strong className="font-semibold text-foreground">Boundary: </strong>{role.restriction}
                      </p>
                    </article>
                  ))}
                </div>
              </section>
            );
          })}

          <section className="rounded-[18px] border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold">Policy notes</h2>
            <ul className="mt-3 list-disc space-y-2 pl-5 text-xs leading-5 text-muted">
              {result.notes.map((note) => <li key={note}>{note}</li>)}
            </ul>
            <div className="mt-4 flex flex-wrap gap-3 border-t border-border pt-4 text-sm">
              <Link href="/admin/users" className="font-semibold text-brand hover:underline">Manage platform users</Link>
              <Link href="/admin/workspaces" className="font-semibold text-brand hover:underline">Browse workspaces</Link>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
