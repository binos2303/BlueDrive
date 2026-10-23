"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { AlertTriangle, History, Search, Trash2, HardDrive, Languages, Plug, Palette } from "lucide-react";
import DashboardShell from "@/components/layout/DashboardShell";
import CustomScrollArea from "@/components/ui/CustomScrollArea";
import { readThemePreference, setThemePreference, type ThemePreference } from "@/lib/theme";
import Button from "@/components/ui/Button";
import {
  clearMySearchHistory,
  deleteMyDriveData,
  getMyActivity,
  getMySearchHistory,
  type SearchHistoryItem,
  type UserActivityEvent,
} from "@/lib/user-settings-service";
import { requestAccountApi } from "@/lib/account-service";

type SettingsTab = "general" | "privacy" | "connections";
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

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
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
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return false;
    const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    // A single selected date filters that day; two dates filter the inclusive range.
    if (dateFrom && dateTo) return day >= dateFrom && day <= dateTo;
    if (dateFrom) return day === dateFrom;
    if (dateTo) return day === dateTo;
    return true;
  }

  const [quota, setQuota] = useState<QuotaSummary | null>(null);
  const [quotaError, setQuotaError] = useState<string | null>(null);
  const [activity, setActivity] = useState<UserActivityEvent[]>([]);
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
    try {
      const [events, history] = await Promise.all([getMyActivity(50), getMySearchHistory(50)]);
      setActivity(events);
      setSearchHistory(history);
    } catch (error) {
      setPrivacyError(error instanceof Error ? error.message : "Could not load privacy data.");
    } finally {
      setPrivacyLoading(false);
    }
  }, []);

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
    <DashboardShell settingsNavigation={{ active: activeTab, onChange: (section) => setActiveTab(section as SettingsTab) }}>
      <section className="mx-auto w-full max-w-5xl p-5 sm:p-8">
        <h1 className="mb-6 text-2xl font-semibold text-foreground">{
          activeTab === "general" ? "General Settings" : activeTab === "privacy" ? "Privacy" : "Connected Apps"
        }</h1>
        <div className="min-w-0">
          {activeTab === "general" ? (
            <div className="divide-y divide-border rounded-2xl border border-border bg-surface px-5 sm:px-7">
              <section className="py-6">
                <div className="flex items-center gap-3"><HardDrive size={19} className="text-brand-contrast" /><h3 className="text-base font-semibold text-foreground">Storage</h3></div>
                {quota?.configured ? (
                  <div className="mt-4 max-w-lg space-y-2">
                    <div className="h-1.5 overflow-hidden rounded-full bg-background" role="progressbar" aria-label="Storage used" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.max(0, Math.min(100, quota.percentUsed ?? 0))}>
                      <div className="h-full rounded-full bg-brand-contrast" style={{ width: `${Math.max(0, Math.min(100, quota.percentUsed ?? 0))}%` }} />
                    </div>
                    <p className="text-[13px] text-muted">{formatBytes(quota.usedBytes)} used{quota.limitBytes == null ? " · No limit" : ` of ${formatBytes(quota.limitBytes)}`}</p>
                  </div>
                ) : <p className="mt-3 text-[13px] text-muted">{quotaError ?? quota?.message ?? "Loading storage information…"}</p>}
              </section>
              <section className="py-6">
                <div className="flex items-center gap-3"><Palette size={19} className="text-brand-contrast" /><h3 className="text-base font-semibold text-foreground">Theme</h3></div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {(["system", "light", "dark"] as const).map((option) => (
                    <button key={option} type="button" onClick={() => changeTheme(option)}
                      aria-pressed={theme === option}
                      className={`rounded-xl border px-4 py-2 text-[13px] font-medium ${theme === option ? "border-brand bg-brand-soft text-brand-contrast" : "border-border bg-background text-foreground"}`}>
                      {option === "system" ? "System" : option === "light" ? "Light" : "Dark"}
                    </button>
                  ))}
                </div>
              </section>
              <section className="py-6">
                <div className="flex items-center gap-3"><Languages size={19} className="text-brand-contrast" /><h3 className="text-base font-semibold text-foreground">Language</h3></div>
                <label className="mt-4 block max-w-xs"><span className="mb-1.5 block text-xs text-muted">Display language</span>
                  <select value="en" disabled className="h-10 w-full rounded-xl border border-border bg-background px-3 text-[13px] text-foreground"><option value="en">English</option></select>
                </label>
              </section>
            </div>
          ) : activeTab === "privacy" ? (
            <div className="space-y-5">
              <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-surface p-4">
                <label className="text-xs text-muted">From
                  <input type="date" value={dateFrom} onChange={(event) => { const value = event.target.value; setDateFrom(value); if (dateTo && value > dateTo) setDateTo(""); }}
                    className="mt-1 block h-9 rounded-lg border border-border bg-background px-2 text-foreground" />
                </label>
                <label className="text-xs text-muted">To
                  <input type="date" value={dateTo} onChange={(event) => { const value = event.target.value; setDateTo(value); if (dateFrom && value < dateFrom) setDateFrom(""); }}
                    className="mt-1 block h-9 rounded-lg border border-border bg-background px-2 text-foreground" />
                </label>
                <button type="button" onClick={() => { setDateFrom(""); setDateTo(""); }} className="h-9 rounded-lg border border-border px-3 text-xs text-foreground">Clear filter</button>
              </div>
          {privacyError && <p role="alert" className="rounded-xl border border-danger/30 bg-surface p-3 text-sm text-danger">{privacyError}</p>}

          <section className="rounded-2xl border border-border bg-surface p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-background text-muted"><History size={19} /></span>
                <div>
                  <h2 className="text-base font-semibold text-foreground">Activity History</h2>
                  
                </div>
              </div>
              <Button variant="secondary" size="sm" onClick={() => void loadPrivacyData()} disabled={privacyLoading}>Refresh</Button>
            </div>
            <CustomScrollArea className="mt-4 rounded-xl border border-border" contentClassName="divide-y divide-border">
              {privacyLoading ? <p className="p-4 text-sm text-muted">Loading activity…</p> : activity.filter((event) => inDateRange(event.createdAt)).length === 0 ? <p className="p-4 text-sm text-muted">No activity recorded yet.</p> : activity.filter((event) => inDateRange(event.createdAt)).map((event) => (
                <article key={event.id} className="flex flex-col gap-1 p-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-foreground">{event.actionLabel || event.action}</p>
                    <p className="mt-0.5 wrap-break-word text-xs leading-5 text-muted">{event.description || event.actionLabel}{event.workspaceName ? ` · ${event.workspaceName}` : event.tenantName ? ` · ${event.tenantName}` : ""}</p>
                  </div>
                  <time className="shrink-0 text-[11px] text-muted">{formatDate(event.createdAt)}</time>
                </article>
              ))}
            </CustomScrollArea>
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
            <CustomScrollArea className="mt-4 rounded-xl border border-border" contentClassName="divide-y divide-border">
              {privacyLoading ? <p className="p-4 text-sm text-muted">Loading search history…</p> : searchHistory.filter((item) => inDateRange(item.createdAt)).length === 0 ? <p className="p-4 text-sm text-muted">No search history yet.</p> : searchHistory.filter((item) => inDateRange(item.createdAt)).map((item) => (
                <article key={item.id} className="flex flex-col gap-1 p-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                  <div className="min-w-0">
                    <p className="wrap-break-word text-sm font-medium text-foreground">{item.query}</p>
                    <p className="mt-0.5 text-xs text-muted">{item.resultCount} results{item.workspaceName ? ` · ${item.workspaceName}` : " · My Drive"}</p>
                  </div>
                  <time className="shrink-0 text-[11px] text-muted">{formatDate(item.createdAt)}</time>
                </article>
              ))}
            </CustomScrollArea>
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
                <span className="text-xs font-semibold text-foreground">Current password</span>
                <input type="password" autoComplete="current-password" value={deletePassword} onChange={(event) => setDeletePassword(event.currentTarget.value)} className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm text-foreground focus:border-brand" />
              </label>
              <label className="flex flex-col gap-2">
                <span className="text-xs font-semibold text-foreground">Type DELETE MY DRIVE to confirm</span>
                <input value={deleteConfirmation} onChange={(event) => setDeleteConfirmation(event.currentTarget.value)} autoCapitalize="characters" className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm text-foreground focus:border-brand" />
              </label>
              {deleteFeedback && <p role="status" className={`text-sm ${deleteFeedback.kind === "success" ? "text-success" : "text-danger"}`}>{deleteFeedback.text}</p>}
              <Button type="submit" variant="destructive" loading={deleteBusy} disabled={deleteBusy || !deletePassword || deleteConfirmation !== "DELETE MY DRIVE"}><Trash2 size={15} /> Delete My Data</Button>
            </form>
          </section>
            </div>
          ) : (
            <section className="rounded-2xl border border-border bg-surface p-6">
              <div className="flex items-center gap-3"><Plug size={19} className="text-brand-contrast" /><h3 className="text-base font-semibold text-foreground">Connected Apps</h3></div>
              <p className="mt-3 text-[13px] text-muted">No connected apps.</p>
              <p className="mt-1 text-xs text-muted">Third-party app connections will be available in a future update.</p>
            </section>
          )}
        </div>
      </section>
    </DashboardShell>
  );
}
