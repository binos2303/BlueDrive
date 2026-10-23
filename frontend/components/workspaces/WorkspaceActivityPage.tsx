"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Clock3, RefreshCw } from "lucide-react";
import { getWorkspaceActivity, type WorkspaceActivityEvent } from "@/lib/workspace-service";

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export default function WorkspaceActivityPage({ workspaceId }: { workspaceId: string }) {
  const [events, setEvents] = useState<WorkspaceActivityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshCount, setRefreshCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const startTimer = window.setTimeout(() => {
      if (!cancelled) {
        setLoading(true);
        setError(null);
      }
    }, 0);
    void getWorkspaceActivity(workspaceId)
      .then((rows) => { if (!cancelled) setEvents(rows); })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "The workspace timeline could not be loaded.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; window.clearTimeout(startTimer); };
  }, [workspaceId, refreshCount]);

  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
      <Link href="/drive" className="inline-flex items-center gap-2 rounded-lg text-sm font-medium text-muted hover:text-foreground">
        <ArrowLeft size={16} /> Back to Drive
      </Link>
      <div className="mt-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-muted"><Clock3 size={16} /> Workspace activity</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">Timeline</h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-muted">Review file and membership events in this workspace. Access is limited to workspace managers.</p>
        </div>
        <button type="button" onClick={() => setRefreshCount((value) => value + 1)} disabled={loading} className="inline-flex h-9 items-center gap-2 rounded-xl border border-border bg-surface px-3 text-xs font-semibold text-foreground hover:bg-background disabled:opacity-50">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="mt-6 overflow-hidden rounded-2xl border border-border bg-surface">
        {loading ? (
          <div className="p-10 text-center text-sm text-muted">Loading workspace activity…</div>
        ) : error ? (
          <div className="p-6">
            <p role="alert" className="text-sm font-semibold text-danger">Timeline could not be loaded</p>
            <p className="mt-1 text-sm leading-6 text-muted">{error}</p>
          </div>
        ) : events.length === 0 ? (
          <div className="p-10 text-center">
            <Clock3 size={24} className="mx-auto text-muted" />
            <p className="mt-3 text-sm font-semibold text-foreground">No activity yet</p>
            <p className="mt-1 text-sm text-muted">Workspace events will appear here as people work with files and members.</p>
          </div>
        ) : (
          <ol className="divide-y divide-border">
            {events.map((event) => (
              <li key={event.id} className="grid gap-2 px-4 py-4 sm:grid-cols-[minmax(0,1fr)_12rem] sm:items-start sm:px-5">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[10px] font-bold text-brand-contrast">{event.username.slice(0, 1).toUpperCase()}</span>
                    <span className="text-sm font-semibold text-foreground">{event.username}</span>
                    <span className="rounded-full border border-border px-2 py-0.5 text-[10px] font-semibold text-muted">{event.actionLabel || event.action}</span>
                  </div>
                  <p className="mt-2 break-words text-sm leading-6 text-foreground">{event.description || event.actionLabel || event.action}</p>
                </div>
                <time className="text-xs text-muted sm:text-right">{formatDate(event.createdAt)}</time>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
