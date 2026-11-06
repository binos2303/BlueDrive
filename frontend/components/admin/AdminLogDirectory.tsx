"use client";

import { useEffect, useState, type FormEvent } from "react";
import { RefreshCw, Search, ScrollText } from "lucide-react";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";
import styles from "./AdminLogDirectory.module.css";

type Mode = "activity" | "audit";
type Filters = { q: string; action: string; scope: string; from: string; to: string };
type LogRow = {
  id: string;
  created_at: string;
  action: string;
  action_label: string;
  user?: string;
  scope?: "personal" | "organization" | "unassigned";
  tenant?: string | null;
  workspace?: string | null;
  personal_drive?: boolean;
  resource_type?: string | null;
  resource_name?: string;
  resource_id?: number | null;
  share?: {
    operation: "created" | "permission_changed" | "mixed" | "revoked" | "unknown";
    recipient: string;
    recipient_username: string;
    permission: string;
    previous_permission: string;
    resources: string[];
    resource_kinds: string[];
    count: number | null;
    created_count: number | null;
    updated_count: number | null;
    changes: { name: string; kind: string; operation: string; permission: string; previous_permission: string }[];
  } | null;
  actor?: string;
  target?: string;
  reason?: string;
};
type LogDirectory = {
  count: number;
  page: number;
  page_size: number;
  actions: { value: string; label: string }[];
  results: LogRow[];
};

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const emptyFilters: Filters = { q: "", action: "all", scope: "all", from: "", to: "" };

function localTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function scopeLabel(row: LogRow) {
  if (row.scope === "organization") return row.tenant || "Organization";
  if (row.scope === "personal") return row.personal_drive ? "Personal Files" : row.workspace ? "Personal workspace" : "Personal storage";
  return "Context not recorded";
}

function shareOperationLabel(row: LogRow) {
  if (row.action === "REVOKE_SHARE") return "Access revoked";
  switch (row.share?.operation) {
    case "created": return "Access granted";
    case "permission_changed": return "Permission changed";
    case "mixed": return "Grants updated";
    default: return "Share (legacy / unspecified)";
  }
}

function ActivityDetailsContent({ row }: { row: LogRow }) {
  const location = scopeLabel(row);
  const share = row.share;
  const detailRows: Array<[string, string]> = [
    ["Event ID", row.id],
    ["Time", localTime(row.created_at)],
    ["Actor", row.user || "Not recorded"],
    ["Action", share ? shareOperationLabel(row) : row.action_label || row.action],
    ["Storage scope", location],
    ["Workspace", row.workspace || "Not recorded"],
  ];
  if (share) {
    detailRows.push(
      ["Recipient", share.recipient || "Not recorded (legacy event)"],
      ["Recipient account", share.recipient_username || "Not recorded"],
      ["Permission", share.permission || "Not recorded"],
      ["Previous permission", share.previous_permission || "Not recorded"],
      ["Resource names", share.resources.length ? share.resources.join(", ") : "Not recorded (legacy event)"],
      ["Resource kinds", share.resource_kinds.length ? share.resource_kinds.join(", ") : "Not recorded"],
      ["Changed items", share.count === null ? "Not recorded" : String(share.count)],
    );
    if (share.created_count !== null) detailRows.push(["New grants", String(share.created_count)]);
    if (share.updated_count !== null) detailRows.push(["Permissions updated", String(share.updated_count)]);
    if (share.changes?.length) {
      detailRows.push(["Per-resource changes", share.changes.map((change) =>
        `${change.kind || "item"}: ${change.name || "Unknown"} · ${change.operation.replaceAll("_", " ")} · ${change.previous_permission ? `${change.previous_permission} → ` : ""}${change.permission}`
      ).join(" | ")]);
    }
  } else {
    detailRows.push(["Resource type", row.resource_type || "Not recorded"]);
    detailRows.push(["Resource name", row.resource_name || "Not recorded (legacy event)"]);
  }
  if (row.resource_id != null) detailRows.push(["Resource ID", String(row.resource_id)]);
  return <EventDetailList rows={detailRows} />;
}

function EventDetailList({ rows }: { rows: Array<[string, string]> }) {
  return (
    <dl className="grid gap-x-4 gap-y-3 text-[13px] sm:grid-cols-[150px_minmax(0,1fr)]">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="font-medium text-muted">{label}</dt>
          <dd className="min-w-0 wrap-break-word text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function AuditDetailsContent({ row }: { row: LogRow }) {
  return <EventDetailList rows={[
    ["Event ID", row.id],
    ["Time", localTime(row.created_at)],
    ["Administrator", row.actor || "Not recorded"],
    ["Action", row.action_label || row.action],
    ["Target account", row.target || "Not recorded"],
    ["Reason", row.reason || "Not recorded"],
  ]} />;
}

export default function AdminLogDirectory({ mode }: { mode: Mode }) {
  const activity = mode === "activity";
  const [draft, setDraft] = useState<Filters>({ ...emptyFilters });
  const [applied, setApplied] = useState<Filters>({ ...emptyFilters });
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<LogDirectory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedRow, setSelectedRow] = useState<LogRow | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const endpoint = activity ? "activity" : "audit";
    const params = new URLSearchParams({ page: String(page), action: applied.action });
    if (applied.q) params.set("q", applied.q);
    if (activity && applied.scope !== "all") params.set("scope", applied.scope);
    if (applied.from) params.set("from", applied.from);
    if (applied.to) params.set("to", applied.to);

    fetch(`${apiBase}/accounts/api/admin/${endpoint}/?${params}`, {
      credentials: "include",
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({})) as { detail?: string };
          throw new Error(body.detail || `Unable to load logs (HTTP ${response.status}).`);
        }
        return response.json() as Promise<LogDirectory>;
      })
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setError("");
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : "Unable to load logs.");
        setLoading(false);
      });
    return () => controller.abort();
  }, [activity, applied, page, revision]);

  const totalPages = Math.max(1, Math.ceil((data?.count ?? 0) / (data?.page_size || 20)));
  const title = activity ? "User Activity" : "Admin Audit Logs";

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSelectedRow(null);
    setApplied({ ...draft, q: draft.q.trim().slice(0, 100) });
    setPage(1);
    setError("");
    setLoading(true);
    setRevision((current) => current + 1);
  }

  function resetFilters() {
    setSelectedRow(null);
    setDraft({ ...emptyFilters });
    setApplied({ ...emptyFilters });
    setPage(1);
    setLoading(true);
    setError("");
    setRevision((current) => current + 1);
  }

  function refresh() {
    setLoading(true);
    setRevision((current) => current + 1);
  }

  function goToPage(next: number) {
    setSelectedRow(null);
    setPage(next);
    setLoading(true);
    setError("");
  }

  return (
    <div className="space-y-5">
      <AdminPageHeader
        title={title}
        actions={
          <Button size="sm" variant="secondary" disabled={loading} onClick={refresh}>
            <RefreshCw size={15} /> Refresh
          </Button>
        }
      />

      <section className={`${styles.filterContainer} overflow-hidden rounded-[20px] border border-border bg-surface`}>
        <form onSubmit={applyFilters} className={`${styles.filterForm} ${activity ? styles.activity : styles.audit} border-b border-border p-4 lg:p-5`}>
          <label className={`${styles.searchField} flex min-w-0 flex-col gap-1 text-[12px] text-muted`}>
            Search {activity ? "user or workspace" : "administrator or target"}
            <span data-admin-search-shell className="flex h-10 min-w-0 items-center gap-2 rounded-xl border border-border bg-background px-3">
              <Search size={15} />
              <input
                type="search"
                value={draft.q}
                onChange={(event) => setDraft((current) => ({ ...current, q: event.target.value }))}
                placeholder={activity ? "Username, email, organization…" : "Administrator or account…"}
                className="min-w-0 w-full bg-transparent text-[13px] text-foreground outline-none"
                maxLength={100}
              />
            </span>
          </label>
          <label className="flex min-w-0 flex-col gap-1 text-[12px] text-muted">
            Action
            <select
              value={draft.action}
              onChange={(event) => setDraft((current) => ({ ...current, action: event.target.value }))}
              className="h-10 min-w-0 w-full rounded-xl border border-border bg-background px-2.5 text-[12px] text-foreground"
            >
              <option value="all">All actions</option>
              {data?.actions.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          {activity && (
            <label className="flex min-w-0 flex-col gap-1 text-[12px] text-muted">
              Storage scope
              <select
                value={draft.scope}
                onChange={(event) => setDraft((current) => ({ ...current, scope: event.target.value }))}
                className="h-10 w-full min-w-0 rounded-xl border border-border bg-background px-2.5 text-[12px] text-foreground"
              >
                <option value="all">All scopes</option>
                <option value="personal">Personal / independent</option>
                <option value="organization">Organizations</option>
                <option value="unassigned">No workspace context</option>
              </select>
            </label>
          )}
          <label className="flex min-w-0 flex-col gap-1 text-[12px] text-muted">
            From
            <input type="date" value={draft.from} max={draft.to || undefined}
              onChange={(event) => setDraft((current) => ({ ...current, from: event.target.value }))}
              className="h-10 min-w-0 w-full rounded-xl border border-border bg-background px-2.5 text-[12px] text-foreground" />
          </label>
          <label className="flex min-w-0 flex-col gap-1 text-[12px] text-muted">
            To
            <input type="date" value={draft.to} min={draft.from || undefined}
              onChange={(event) => setDraft((current) => ({ ...current, to: event.target.value }))}
              className="h-10 min-w-0 w-full rounded-xl border border-border bg-background px-2.5 text-[12px] text-foreground" />
          </label>
          <div className={`${styles.filterActions} flex min-w-0 flex-wrap items-center gap-2`}>
            <Button size="sm" type="submit" disabled={loading}>Apply filters</Button>
            <button type="button" className="rounded-lg px-3 py-2 text-[12px] text-muted hover:bg-background hover:text-foreground" onClick={resetFilters}>Clear</button>
          </div>
        </form>

        {error && <div role="alert" className="p-6 text-[13px] text-danger">{error}</div>}
        {loading && <div role="status" className="p-10 text-center text-[13px] text-muted">Loading {activity ? "user activity" : "audit events"}…</div>}
        {!loading && !error && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-212.5 text-left text-[13px]">
              <thead className="bg-background text-[11px] font-semibold uppercase tracking-wide text-muted">
                {activity ? (
                  <tr>
                    <th scope="col" className="px-5 py-3">Time</th>
                    <th scope="col" className="px-5 py-3">User</th>
                    <th scope="col" className="px-5 py-3">Action</th>
                    <th scope="col" className="px-5 py-3">Location</th>
                    <th scope="col" className="px-5 py-3">Resource / Recipient</th>
                  </tr>
                ) : (
                  <tr>
                    <th scope="col" className="px-5 py-3">Time</th>
                    <th scope="col" className="px-5 py-3">Administrator</th>
                    <th scope="col" className="px-5 py-3">Action</th>
                    <th scope="col" className="px-5 py-3">Target account</th>
                    <th scope="col" className="px-5 py-3">Reason</th>
                  </tr>
                )}
              </thead>
              <tbody>
                {data?.results.map((row) => (
                  <tr
                    key={row.id}
                    tabIndex={0}
                    aria-haspopup="dialog"
                    aria-label={`Event ${row.action_label || row.action}, ${localTime(row.created_at)}. Double-click for details; press Enter to open.`}
                    title="Double-click to view event details"
                    onDoubleClick={() => setSelectedRow(row)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedRow(row);
                      }
                    }}
                    className="cursor-pointer border-t border-border/70 align-top transition-colors hover:bg-background/60 focus-visible:bg-brand-soft focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand"
                  >
                    <td className="whitespace-nowrap px-5 py-3 text-[12px] text-muted">{localTime(row.created_at)}</td>
                    <td className="px-5 py-3 font-medium">{activity ? (row.user || "—") : (row.actor || "—")}</td>
                    <td className="px-5 py-3"><span className="inline-flex rounded-lg bg-brand-soft px-2.5 py-1 text-[12px] font-medium text-brand-contrast">{activity && row.share ? shareOperationLabel(row) : row.action_label || row.action}</span></td>
                    {activity ? (
                      <>
                        <td className="px-5 py-3"><p>{scopeLabel(row)}</p>{row.workspace && <p className="mt-1 text-[12px] text-muted">{row.workspace}</p>}</td>
                        <td className="min-w-75 max-w-120 px-5 py-3 text-muted">
                          {row.share ? (
                            <>
                              <p className="wrap-break-word text-foreground">{row.share.resources.length ? row.share.resources.join(", ") : "Resource not recorded"}</p>
                              <p className="mt-1 text-[12px]">Recipient: {row.share.recipient || "Not recorded (legacy event)"}</p>
                              <p className="mt-1 text-[11px]">{row.share.previous_permission ? `${row.share.previous_permission} → ` : ""}{row.share.permission || "Permission not recorded"}{row.share.count !== null ? ` · ${row.share.count} changed` : ""}</p>
                            </>
                          ) : <p>{row.resource_name || (row.resource_type ? `${row.resource_type}${row.resource_id != null ? ` #${row.resource_id}` : ""}` : "Resource not recorded")}</p>}
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-5 py-3">{row.target || "—"}</td>
                        <td className="max-w-80 wrap-break-word px-5 py-3 text-muted">{row.reason || "—"}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {data?.results.length === 0 && (
              <div className="flex flex-col items-center p-10 text-center text-muted">
                <ScrollText size={26} />
                <p className="mt-3 text-sm font-semibold text-foreground">No matching events</p>
                <p className="mt-1 text-xs">Try another action, date range or search term.</p>
              </div>
            )}
          </div>
        )}

        {!loading && !error && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-4 text-[12px]">
            <span className="text-muted">{(data?.count || 0).toLocaleString()} recorded events · Page {page} of {totalPages}</span>
            <div className="flex gap-2">
              <button type="button" disabled={page <= 1} onClick={() => goToPage(page - 1)} className="rounded-lg border border-border px-3 py-2 disabled:opacity-40">Previous</button>
              <button type="button" disabled={page >= totalPages} onClick={() => goToPage(page + 1)} className="rounded-lg border border-border px-3 py-2 disabled:opacity-40">Next</button>
            </div>
          </div>
        )}
      </section>
      <Dialog
        open={selectedRow !== null}
        title={activity ? "Activity details" : "Audit event details"}
        description={selectedRow ? `${selectedRow.action_label || selectedRow.action} · ${localTime(selectedRow.created_at)}` : undefined}
        onClose={() => setSelectedRow(null)}
      >
        {selectedRow && (activity
          ? <ActivityDetailsContent row={selectedRow} />
          : <AuditDetailsContent row={selectedRow} />)}
      </Dialog>
    </div>
  );
}
