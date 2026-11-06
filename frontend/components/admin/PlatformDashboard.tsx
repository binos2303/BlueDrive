"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import {
  Activity, ArrowRight, Building2, Database, FileText, HardDrive, RefreshCw, Users, Workflow,
} from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

type Overview = {
  users: { total: number; active: number; inactive: number; platform_admins: number; recently_seen: number };
  organizations: { total: number; active: number };
  workspaces: { total: number; active: number; organization: number; personal: number };
  files: { total: number; metadata_bytes: number; in_trash: number };
  health: { api: "responding"; database: "responding"; minio: "not_monitored" };
};

const formatNumber = (n: number | undefined) => n === undefined ? "—" : new Intl.NumberFormat("en-US").format(n);
function formatBytes(n: number | undefined) {
  if (n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB", "PB"];
  let amount = n / 1024;
  let i = 0;
  while (amount >= 1024 && i < units.length - 1) { amount /= 1024; i++; }
  return `${amount.toFixed(amount >= 10 ? 1 : 2)} ${units[i]}`;
}

function MetricCard({ label, value, details, href, icon: Icon }: {
  label: string; value: string; details: string; href: string; icon: typeof Users;
}) {
  return <Link href={href} className="group flex min-h-39 flex-col justify-between rounded-[20px] border border-border bg-surface p-5 transition-colors duration-(--motion-fast) hover:bg-brand-soft/30 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
    <div className="flex items-start justify-between gap-3"><span className="text-[13px] font-medium text-muted">{label}</span><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-contrast"><Icon size={19} /></span></div>
    <div><p className="mt-3 text-[28px] font-semibold tracking-tight text-foreground">{value}</p><div className="mt-2 flex items-center justify-between gap-2"><p className="text-xs text-muted">{details}</p><ArrowRight size={15} className="shrink-0 text-muted transition-transform group-hover:translate-x-1" /></div></div>
  </Link>;
}

function Section({ title, description, children, href, label }: {
  title: string; description?: string; children: ReactNode; href?: string; label?: string;
}) {
  return <section className="overflow-hidden rounded-[20px] border border-border bg-surface">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-4"><div><h3 className="text-[14px] font-semibold">{title}</h3>{description && <p className="mt-1 text-[11px] text-muted">{description}</p>}</div>{href && <Link href={href} className="inline-flex items-center gap-1 text-xs font-semibold text-brand-contrast hover:underline">{label || "View details"}<ArrowRight size={14} /></Link>}</div>
    {children}
  </section>;
}

function DataRow({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between gap-4 border-b border-border/60 px-5 py-3.5 text-[13px] last:border-0"><span className="text-muted">{label}</span><span className="font-semibold tabular-nums">{value}</span></div>;
}

export default function PlatformDashboard() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => { setRevision((v) => v + 1); setLoading(true); }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiBase}/accounts/api/admin/overview/`, { credentials: "include", cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 403
          ? "Administrator access was denied. Please sign in again."
          : `Could not load platform overview (HTTP ${response.status}).`);
        return response.json() as Promise<Overview>;
      })
      .then((data) => { if (!controller.signal.aborted) { setOverview(data); setError(""); setLoading(false); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted) { setOverview(null); setError(reason instanceof Error ? reason.message : "Failed to load overview."); setLoading(false); } });
    return () => controller.abort();
  }, [revision]);

  return <div className="space-y-5">
    <AdminPageHeader title="Dashboard" actions={<button type="button" disabled={loading} onClick={refresh} className="inline-flex h-9 items-center gap-2 rounded-xl border border-border bg-surface px-3 text-xs font-medium transition hover:bg-brand-soft disabled:opacity-50"><RefreshCw size={14} className={loading ? "animate-spin" : ""} />Refresh</button>} />
    {error && <div role="alert" className="rounded-xl border border-danger/30 bg-surface px-4 py-3 text-[13px] text-danger"><p className="font-semibold">Unable to load dashboard</p><p className="mt-1">{error}</p><p className="mt-1 text-muted">Check that the Django endpoint /accounts/api/admin/overview/ is registered.</p></div>}
    <div role={loading ? "status" : undefined} aria-label={loading ? "Loading platform overview" : undefined} className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-4">
      <MetricCard label="User accounts" value={formatNumber(overview?.users.total)} details="Regular users" href="/admin/users" icon={Users} />
      <MetricCard label="Organizations" value={formatNumber(overview?.organizations.total)} details="Registered organizations" href="/admin/organizations" icon={Building2} />
      <MetricCard label="Workspaces" value={formatNumber(overview?.workspaces.total)} details="Active collaboration spaces" href="/admin/workspaces" icon={Workflow} />
      <MetricCard label="Stored files" value={formatNumber(overview?.files.total)} details="Available files" href="/admin/files" icon={FileText} />
    </div>
    <div className="grid gap-5 xl:grid-cols-2">
      <Section title="Accounts" href="/admin/users" label="Open users">
        <DataRow label="Enabled users" value={formatNumber(overview?.users.active)} />
        <DataRow label="Disabled users" value={formatNumber(overview?.users.inactive)} />
        <DataRow label="Users seen in the last 5 min" value={formatNumber(overview?.users.recently_seen)} />
        <DataRow label="Platform admin accounts" value={formatNumber(overview?.users.platform_admins)} />
      </Section>
      <Section title="Workspaces" href="/admin/workspaces" label="Open workspaces">
        <DataRow label="Active workspaces" value={formatNumber(overview?.workspaces.active)} />
        <DataRow label="Organization workspaces" value={formatNumber(overview?.workspaces.organization)} />
        <DataRow label="Personal-tenant workspaces" value={formatNumber(overview?.workspaces.personal)} />
      </Section>
      <Section title="Files" href="/admin/infrastructure/quotas" label="Storage & quotas">
        <DataRow label="Active file metadata" value={formatBytes(overview?.files.metadata_bytes)} />
        <DataRow label="Files in Trash" value={formatNumber(overview?.files.in_trash)} />
        <DataRow label="Active organizations" value={formatNumber(overview?.organizations.active)} />
      </Section>
      <Section title="Service status" href="/admin/infrastructure/topology" label="Storage topology">
        <div className="flex items-center gap-3 border-b border-border/60 px-5 py-3.5"><Activity size={17} className="text-brand-contrast" /><span className="flex-1 text-[13px]">Django API</span><span className="text-xs font-semibold">{overview ? "Responding" : "—"}</span></div>
        <div className="flex items-center gap-3 border-b border-border/60 px-5 py-3.5"><Database size={17} className="text-brand-contrast" /><span className="flex-1 text-[13px]">PostgreSQL</span><span className="text-xs font-semibold">{overview ? "Responding" : "—"}</span></div>
        <div className="flex items-center gap-3 px-5 py-3.5"><HardDrive size={17} className="text-muted" /><span className="flex-1 text-[13px]">MinIO / storage nodes</span><span className="text-xs text-muted">Not monitored</span></div>
      </Section>
    </div>
  </div>;
}
