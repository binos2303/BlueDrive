"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, History, Search, Trash2, HardDrive, Languages, Plug, Palette, Monitor, Moon, Sun } from "lucide-react";
import DashboardShell from "@/components/layout/DashboardShell";
import AccountSecurityPanel from "@/components/account/AccountSecurityPanel";
import AccountProfilePanel from "@/components/account/AccountProfilePanel";
import CustomScrollArea from "@/components/ui/CustomScrollArea";
import { readThemePreference, setThemePreference, type ThemePreference } from "@/lib/theme";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";
import {
  clearMySearchHistory,
  deleteMyDriveData,
  getMyActivity,
  getMySearchHistory,
  type SearchHistoryItem,
  type UserActivityEvent,
} from "@/lib/user-settings-service";
import { requestAccountApi } from "@/lib/account-service";
import { inLocalDateRange } from "@/lib/date-range";
import { settingsTab, type SettingsTab } from "@/lib/account-settings-navigation";
import styles from "@/components/account/AccountSettings.module.css";

const sections = {
  general: { title: "General Settings", description: "Manage My Drive storage, appearance and language." },
  security: { title: "Profile & Security", description: "Manage your account details and password." },
  privacy: { title: "Privacy", description: "Review your activity, search history and personal data controls." },
  connections: { title: "Connected Apps", description: "Review applications connected to your BlueDrive account." },
} satisfies Record<SettingsTab, { title: string; description: string }>;
type QuotaSummary = { configured: boolean; limitBytes: number | null; usedBytes: number | null; percentUsed: number | null; message?: string };
function formatBytes(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value / 1024;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) { amount /= 1024; index++; }
  return `${amount.toFixed(amount >= 10 ? 0 : 1)} ${units[index]}`;
}
function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export default function AccountSettingsContent({ initialTab = "general" }: { initialTab?: SettingsTab }) {
  const router = useRouter();
  const activeTab = initialTab;
  const [theme, setTheme] = useState<ThemePreference>("system");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setTheme(readThemePreference()), 0);
    return () => window.clearTimeout(timer);
  }, []);
  function changeTheme(next: ThemePreference) {
    setTheme(next);
    setThemePreference(next);
  }
  function inDateRange(value: string): boolean {
    return inLocalDateRange(value, dateFrom, dateTo);
  }

  const [quota, setQuota] = useState<QuotaSummary | null>(null);
  const [quotaError, setQuotaError] = useState<string | null>(null);
  const [activity, setActivity] = useState<UserActivityEvent[]>([]);
  const [activityHasMore, setActivityHasMore] = useState(false);
  const [searchHasMore, setSearchHasMore] = useState(false);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [activityLoadingMore, setActivityLoadingMore] = useState(false);
  const [searchLoadingMore, setSearchLoadingMore] = useState(false);
  const [selectedActivity, setSelectedActivity] = useState<UserActivityEvent | null>(null);
  const [searchHistory, setSearchHistory] = useState<SearchHistoryItem[]>([]);
  const [privacyLoading, setPrivacyLoading] = useState(false);
  const [privacyError, setPrivacyError] = useState<string | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteFeedback, setDeleteFeedback] = useState<{ kind: "success" | "error"; text: string } | null>(null);


  const loadPrivacyData = useCallback(async () => {
    setPrivacyLoading(true);
    setPrivacyError(null);
    setActivityError(null);
    setSearchError(null);
    // Separate failures: an unavailable Activity endpoint must never hide Search History.
    const [activityResult, searchResult] = await Promise.allSettled([
      getMyActivity(50),
      getMySearchHistory(50),
    ]);
    if (activityResult.status === "fulfilled") {
      setActivity(activityResult.value.events);
      setActivityHasMore(activityResult.value.hasMore);
    } else {
      setActivityError(activityResult.reason instanceof Error ? activityResult.reason.message : "Could not load activity history.");
    }
    if (searchResult.status === "fulfilled") {
      setSearchHistory(searchResult.value.items);
      setSearchHasMore(searchResult.value.hasMore);
    } else {
      setSearchError(searchResult.reason instanceof Error ? searchResult.reason.message : "Could not load search history.");
    }
    setPrivacyLoading(false);
  }, []);

  async function loadOlderActivity() {
    if (activityLoadingMore || !activityHasMore) return;
    setActivityLoadingMore(true);
    setActivityError(null);
    try {
      const next = await getMyActivity(50, activity.length);
      setActivity((previous) => [...previous, ...next.events.filter((event) => !previous.some((existing) => existing.id === event.id))]);
      setActivityHasMore(next.hasMore);
    } catch (error) {
      setActivityError(error instanceof Error ? error.message : "Could not load older activity.");
    } finally {
      setActivityLoadingMore(false);
    }
  }

  async function loadOlderSearches() {
    if (searchLoadingMore || !searchHasMore) return;
    setSearchLoadingMore(true);
    setSearchError(null);
    try {
      const next = await getMySearchHistory(50, searchHistory.length);
      setSearchHistory((previous) => [...previous, ...next.items.filter((item) => !previous.some((existing) => existing.id === item.id))]);
      setSearchHasMore(next.hasMore);
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : "Could not load older searches.");
    } finally {
      setSearchLoadingMore(false);
    }
  }

  useEffect(() => {
    if (activeTab !== "privacy") return;
    const timer = window.setTimeout(() => { void loadPrivacyData(); }, 0);
    return () => window.clearTimeout(timer);
  }, [activeTab, loadPrivacyData]);


  async function handleClearHistory() {
    if (!window.confirm("Clear your search history? This cannot be undone.")) return;
    setHistoryBusy(true);
    setPrivacyError(null);
    try {
      await clearMySearchHistory();
      setSearchHistory([]);
      setSearchHasMore(false);
      setSearchError(null);
    } catch (error) {
      setPrivacyError(error instanceof Error ? error.message : "Could not clear search history.");
    } finally {
      setHistoryBusy(false);
    }
  }

  async function handleDeleteMyDrive(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setDeleteFeedback(null);
    if (deleteConfirmation !== "DELETE MY DRIVE") {
      setDeleteFeedback({ kind: "error", text: 'Enter "DELETE MY DRIVE" exactly to confirm.' });
      return;
    }
    if (!deletePassword) {
      setDeleteFeedback({ kind: "error", text: "Enter your current password." });
      return;
    }
    const confirmed = window.confirm("This permanently deletes your personal My Drive files and folders, not shared workspace data. Continue?");
    if (!confirmed) return;

    setDeleteBusy(true);
    try {
      const result = await deleteMyDriveData({ password: deletePassword, confirmation: "DELETE MY DRIVE" });
      setDeletePassword("");
      setDeleteConfirmation("");
      setDeleteFeedback({ kind: "success", text: `Deleted ${result.filesDeleted} files and ${result.foldersDeleted} folders from My Drive. Security logs were retained.` });
      await loadPrivacyData();
      window.dispatchEvent(new Event("securedrive:folder-tree-refresh"));
    } catch (error) {
      setDeleteFeedback({ kind: "error", text: error instanceof Error ? error.message : "Could not delete My Drive data." });
    } finally {
      setDeleteBusy(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    requestAccountApi<QuotaSummary>("/accounts/api/me/quota/")
      .then((value) => { if (!cancelled) setQuota(value); })
      .catch((error: unknown) => { if (!cancelled) setQuotaError(error instanceof Error ? error.message : "Storage information is unavailable."); });
    return () => { cancelled = true; };
  }, []);
  return (
    <DashboardShell settingsNavigation={{ active: activeTab, onChange: (section) => router.push(`/account/settings?section=${settingsTab(section)}`) }}>
      <section className={`${styles.page} mx-auto w-full max-w-5xl space-y-5 px-4 py-4 sm:px-6 sm:py-5`}>
        <div><h1 id="account-settings-title" className="text-2xl font-semibold tracking-tight text-foreground">{sections[activeTab].title}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">{sections[activeTab].description}</p></div>
        <div id="account-settings-panel" aria-labelledby="account-settings-title" className="min-w-0">
          {activeTab === "general" ? (
            <div className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-surface">
              <section className={styles.preference}>
                <div><div className="flex items-center gap-3"><HardDrive size={19} className="shrink-0 text-brand-contrast" /><h2 className="text-base font-semibold">Storage</h2></div>
                  <p className="mt-2 text-sm leading-6 text-muted">Space used by your personal My Drive.</p></div>
                {quota?.configured ? (
                  <div className="space-y-3">
                    <div className="flex flex-wrap justify-between gap-2 text-sm"><span><strong className="font-semibold tabular-nums">{formatBytes(quota.usedBytes)}</strong><span className="text-muted"> used</span></span><span className="text-muted">{quota.limitBytes == null ? "No limit" : `${formatBytes(quota.limitBytes)} total`}</span></div>
                    <div className="h-2 overflow-hidden rounded-full bg-background" role="progressbar" aria-label="My Drive storage used" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.max(0, Math.min(100, quota.percentUsed ?? 0))}>
                      <div className="h-full rounded-full bg-brand-contrast" style={{ width: `${Math.max(0, Math.min(100, quota.percentUsed ?? 0))}%` }} />
                    </div>
                  </div>
                ) : <p role={quotaError ? "alert" : "status"} className={`text-sm leading-6 ${quotaError ? "text-danger" : "text-muted"}`}>{quotaError ?? quota?.message ?? (quota ? "Storage information is not available." : "Loading storage information…")}</p>}
              </section>
              <section className={styles.preference}>
                <div><div className="flex items-center gap-3"><Palette size={19} className="shrink-0 text-brand-contrast" /><h2 className="text-base font-semibold">Appearance</h2></div>
                  <p className="mt-2 text-sm leading-6 text-muted">Choose a theme. Changes apply immediately.</p></div>
                <div className="grid grid-cols-3 gap-2" role="group" aria-label="Color theme">
                  {([{ value: "system", label: "System", icon: Monitor }, { value: "light", label: "Light", icon: Sun }, { value: "dark", label: "Dark", icon: Moon }] as const).map(({ value, label, icon: Icon }) => (
                    <button key={value} type="button" onClick={() => changeTheme(value)} aria-pressed={theme === value}
                      className={`ui-control flex min-h-11 min-w-0 flex-wrap items-center justify-center gap-2 rounded-xl border px-2 py-2 text-sm font-medium transition-colors ${theme === value ? "border-brand-contrast bg-brand-soft text-brand-contrast" : "border-border bg-background text-foreground hover:border-border-strong"}`}><Icon size={17} className="shrink-0" />{label}</button>
                  ))}
                </div>
              </section>
              <section className={styles.preference}>
                <div><div className="flex items-center gap-3"><Languages size={19} className="shrink-0 text-brand-contrast" /><h2 className="text-base font-semibold">Language</h2></div>
                  <p className="mt-2 text-sm leading-6 text-muted">English is currently the available display language.</p></div>
                <label className="block"><span className="mb-2 block text-[13px] font-medium text-muted">Display language</span>
                  <select value="en" disabled className="h-11 w-full min-w-0 rounded-xl border border-border bg-background px-3 text-sm text-foreground disabled:opacity-70"><option value="en">English</option></select>
                </label>
              </section>
            </div>
          ) : activeTab === "security" ? (
            <div className="space-y-5"><AccountProfilePanel /><AccountSecurityPanel /></div>
          ) : activeTab === "privacy" ? (
            <div className="space-y-5">

          {privacyError && <p role="alert" className="rounded-xl border border-danger/30 bg-surface p-3 text-sm text-danger">{privacyError}</p>}

          <section className="rounded-2xl border border-border bg-surface p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-background text-muted"><History size={19} /></span>
                <div>
                  <h2 className="text-base font-semibold text-foreground">Activity History</h2>

                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="secondary" size="sm" onClick={() => void loadPrivacyData()} disabled={privacyLoading}>Refresh</Button>
              </div>
            </div>
              <div className={styles.dateFilters}>
                <label className="text-xs text-muted">From
                  <input type="date" value={dateFrom} onChange={(event) => { const value = event.target.value; setDateFrom(value); if (dateTo && value > dateTo) setDateTo(""); }}
                    className="rounded-xl border border-border bg-background px-3 text-sm text-foreground" />
                </label>
                <label className="text-xs text-muted">To
                  <input type="date" value={dateTo} onChange={(event) => { const value = event.target.value; setDateTo(value); if (dateFrom && value < dateFrom) setDateFrom(""); }}
                    className="rounded-xl border border-border bg-background px-3 text-sm text-foreground" />
                </label>
                <Button variant="secondary" disabled={!dateFrom && !dateTo} onClick={() => { setDateFrom(""); setDateTo(""); }}>Clear filter</Button>
              </div>
            {activityError && <p role="alert" className="mt-3 text-xs text-danger">{activityError}</p>}
            <CustomScrollArea className={`${styles.history} mt-5 rounded-xl border border-border`} contentClassName="divide-y divide-border">
              {privacyLoading ? <p role="status" className="p-4 text-sm text-muted">Loading activity…</p> : activityError && activity.length === 0 ? <Button variant="secondary" size="sm" className="m-4" onClick={() => void loadPrivacyData()}>Retry activity</Button> : activity.filter((event) => inDateRange(event.createdAt)).length === 0 ? <p className="p-4 text-sm text-muted">{dateFrom || dateTo ? "No activity in the selected date range. Clear the date filter or load older activity." : "No activity recorded yet."}</p> : activity.filter((event) => inDateRange(event.createdAt)).map((event) => (
                <button
                  type="button"
                  key={event.id}
                  aria-haspopup="dialog"
                  aria-label={`View ${event.actionLabel || event.action}, ${formatDate(event.createdAt)}`}
                  title="View activity details"
                  onClick={() => setSelectedActivity(event)}
                  className="flex w-full cursor-pointer flex-col gap-1 p-4 text-left transition-colors hover:bg-background/60 focus-visible:bg-brand-soft focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-contrast sm:flex-row sm:items-start sm:justify-between sm:gap-4"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-foreground">{event.actionLabel || event.action}</p>
                    <p className="mt-0.5 wrap-break-word text-xs leading-5 text-muted">{event.description || event.actionLabel}{event.workspaceName ? ` · ${event.workspaceName}` : event.tenantName ? ` · ${event.tenantName}` : ""}
                      {(event.action === "SHARE" || event.action === "REVOKE_SHARE") && <span className="block">
                        Recipient: {(typeof event.metadata.recipient_email === "string" && event.metadata.recipient_email) || "Not recorded (legacy event)"}
                        {typeof event.metadata.permission === "string" ? ` · ${event.metadata.permission}` : ""}
                      </span>}</p>

                  </div>
                  <time className="shrink-0 text-xs text-muted">{formatDate(event.createdAt)}</time>
                </button>
              ))}
            </CustomScrollArea>
            {activityHasMore && <div className="mt-3 flex justify-center">
              <Button variant="secondary" size="sm" loading={activityLoadingMore} disabled={activityLoadingMore || privacyLoading} onClick={() => void loadOlderActivity()}>Load older activity</Button>
            </div>}
          </section>

          <section className="rounded-2xl border border-border bg-surface p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-background text-muted"><Search size={19} /></span>
                <div>
                  <h2 className="text-base font-semibold text-foreground">Search History</h2>

                </div>
              </div>
              <Button variant="secondary" size="sm" loading={historyBusy} disabled={historyBusy || searchHistory.length === 0} onClick={() => void handleClearHistory()}>Clear history</Button>
            </div>
            {searchError && <p role="alert" className="mt-3 text-xs text-danger">{searchError}</p>}
            <CustomScrollArea className={`${styles.history} mt-5 rounded-xl border border-border`} contentClassName="divide-y divide-border">
              {privacyLoading ? <p role="status" className="p-4 text-sm text-muted">Loading search history…</p> : searchError && searchHistory.length === 0 ? <Button variant="secondary" size="sm" className="m-4" onClick={() => void loadPrivacyData()}>Retry search history</Button> : searchHistory.length === 0 ? <p className="p-4 text-sm text-muted">No search history yet.</p> : searchHistory.map((item) => (
                <article key={item.id} className="flex flex-col gap-1 p-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                  <div className="min-w-0">
                    <p className="wrap-break-word text-sm font-medium text-foreground">{item.query}</p>
                    <p className="mt-0.5 text-xs text-muted">{item.resultCount} results{item.workspaceName ? ` · ${item.workspaceName}` : " · My Drive"}</p>
                  </div>
                  <time className="shrink-0 text-xs text-muted">{formatDate(item.createdAt)}</time>
                </article>
              ))}
            </CustomScrollArea>
            {searchHasMore && <div className="mt-3 flex justify-center">
              <Button variant="secondary" size="sm" loading={searchLoadingMore} disabled={searchLoadingMore || privacyLoading} onClick={() => void loadOlderSearches()}>Load older searches</Button>
            </div>}
          </section>

          <section className="rounded-2xl border border-danger/30 bg-surface p-5 sm:p-6">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-danger/10 text-danger"><AlertTriangle size={19} /></span>
              <h2 className="text-base font-semibold text-foreground">Delete My Data</h2>
            </div>
            <div className="mt-4 rounded-xl border border-danger/20 bg-danger/5 p-3 text-xs leading-5 text-muted">
              Enter your current password and type <strong className="text-foreground">DELETE MY DRIVE</strong> to confirm. This permanently deletes personal My Drive files and folders, not shared workspace data.
            </div>
            <form className="mt-5 max-w-md space-y-4" onSubmit={(event) => { void handleDeleteMyDrive(event); }}>
              <label className="flex flex-col gap-2">
                <span className="text-sm font-medium text-foreground">Current password</span>
                <input type="password" autoComplete="current-password" value={deletePassword} onChange={(event) => setDeletePassword(event.currentTarget.value)} className="h-11 w-full rounded-xl border border-border bg-background px-3 text-sm text-foreground focus:border-brand" />
              </label>
              <label className="flex flex-col gap-2">
                <span className="text-sm font-medium text-foreground">Type DELETE MY DRIVE to confirm</span>
                <input value={deleteConfirmation} onChange={(event) => setDeleteConfirmation(event.currentTarget.value)} autoCapitalize="characters" className="h-11 w-full rounded-xl border border-border bg-background px-3 text-sm text-foreground focus:border-brand" />
              </label>
              {deleteFeedback && <p role={deleteFeedback.kind === "error" ? "alert" : "status"} className={`text-sm ${deleteFeedback.kind === "success" ? "text-success" : "text-danger"}`}>{deleteFeedback.text}</p>}
              <Button type="submit" variant="destructive" loading={deleteBusy} disabled={deleteBusy || !deletePassword || deleteConfirmation !== "DELETE MY DRIVE"}><Trash2 size={15} /> Delete My Data</Button>
            </form>
          </section>
            </div>
          ) : (
            <section className="rounded-2xl border border-border bg-surface p-6">
              <div className="flex items-center gap-3"><Plug size={19} className="text-brand-contrast" /><h2 className="text-base font-semibold text-foreground">Connected Apps</h2></div>
              <p className="mt-3 text-[13px] text-muted">No connected apps.</p>
              <p className="mt-1 text-xs text-muted">Third-party app connections will be available in a future update.</p>
            </section>
          )}
        </div>
      </section>
      <Dialog
        open={selectedActivity !== null}
        title="Activity details"
        description={selectedActivity ? `${selectedActivity.actionLabel || selectedActivity.action} · ${formatDate(selectedActivity.createdAt)}` : undefined}
        onClose={() => setSelectedActivity(null)}
      >
        {selectedActivity && (
          <dl className="grid gap-x-4 gap-y-3 text-[13px] sm:grid-cols-[145px_minmax(0,1fr)]">
            {([
              ["Event ID", String(selectedActivity.id)],
              ["Time", formatDate(selectedActivity.createdAt)],
              ["Action", selectedActivity.actionLabel || selectedActivity.action],
              ["Description", selectedActivity.description || "Not recorded"],
              ["Storage", selectedActivity.workspaceName || selectedActivity.tenantName || "Not recorded"],
              ...((selectedActivity.action === "UPLOAD" || selectedActivity.action === "DOWNLOAD") ? [
                ["File", typeof selectedActivity.metadata.resource_name === "string" ? selectedActivity.metadata.resource_name : "Not recorded"],
                ["File size", typeof selectedActivity.metadata.size_bytes === "number" ? formatBytes(selectedActivity.metadata.size_bytes) : "Not recorded"],
              ] : []),
              ...((selectedActivity.action === "SHARE" || selectedActivity.action === "REVOKE_SHARE") ? [
                ["Change", typeof selectedActivity.metadata.operation === "string" ? selectedActivity.metadata.operation.replaceAll("_", " ") : "Not recorded (legacy event)"],
                ["Recipient", typeof selectedActivity.metadata.recipient_email === "string" ? selectedActivity.metadata.recipient_email : "Not recorded (legacy event)"],
                ["Permission", typeof selectedActivity.metadata.permission === "string" ? selectedActivity.metadata.permission : "Not recorded"],
                ["Previous permission", typeof selectedActivity.metadata.previous_permission === "string" ? selectedActivity.metadata.previous_permission : "Not recorded"],
                ["Resources", Array.isArray(selectedActivity.metadata.resource_names) ? selectedActivity.metadata.resource_names.filter((name): name is string => typeof name === "string").join(", ") || "Not recorded" : "Not recorded"],
              ] : []),
            ] as Array<[string, string]>).map(([label, value]) => (
              <div className="contents" key={label}>
                <dt className="font-medium text-muted">{label}</dt>
                <dd className="min-w-0 break-words text-foreground">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </Dialog>
    </DashboardShell>
  );
}
