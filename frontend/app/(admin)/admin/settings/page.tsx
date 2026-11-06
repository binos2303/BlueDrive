"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { Save, Settings2, ShieldCheck } from "lucide-react";
import AdminBreadcrumb from "@/components/layout/AdminBreadcrumb";
import {
  ADMIN_CONSOLE_NAME_UPDATED,
  getAdminSettings,
  saveAdminSettings,
  type AdminSettingsResponse,
} from "@/lib/admin-settings-service";
import { effectiveSessionPolicy, validateAdminSettingsDraft } from "@/lib/admin-settings-policy";

const inputClass = "mt-2 w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-60";

export default function SettingsPage() {
  const [settings, setSettings] = useState<AdminSettingsResponse | null>(null);
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getAdminSettings(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setSettings(result);
      setName(result.display_name);
      setReason("");
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Unable to read platform settings.");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, []);

  const validation = settings ? validateAdminSettingsDraft({ display_name: name, reason, revision: settings.revision }, settings.display_name) : "Settings are not loaded.";
  const canSave = Boolean(settings?.can_edit && !validation && !loading && !saving);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings?.can_edit || validation || saving) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const result = await saveAdminSettings({ display_name: name, reason, revision: settings.revision });
      setSettings(result);
      setName(result.display_name);
      setReason("");
      setMessage("Console settings saved and audited.");
      window.dispatchEvent(new CustomEvent(ADMIN_CONSOLE_NAME_UPDATED, { detail: result.display_name }));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Settings update failed.");
    } finally {
      setSaving(false);
    }
  }

  function reload() {
    setLoading(true);
    setError("");
    setMessage("");
    void getAdminSettings().then((result) => {
      setSettings(result);
      setName(result.display_name);
      setReason("");
    }).catch((failure: unknown) => {
      setError(failure instanceof Error ? failure.message : "Unable to refresh platform settings.");
    }).finally(() => setLoading(false));
  }

  return <>
    <AdminBreadcrumb />
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-2xl font-semibold text-foreground">System settings</h1>
      <button type="button" onClick={reload} disabled={loading || saving} className="rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-background disabled:opacity-60">Refresh</button>
    </div>
    <div className="max-w-3xl space-y-5">
      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>}
      {message && <p role="status" className="rounded-lg border border-border px-4 py-3 text-sm text-foreground">{message}</p>}
      <section className="rounded-2xl border border-border bg-surface p-5 shadow-sm sm:p-6">
        <div className="flex items-center gap-3">
          <span className="rounded-xl bg-blue-50 p-2.5 text-blue-600"><Settings2 size={18} /></span>
          <div><h2 className="text-sm font-semibold text-foreground">Console identity</h2><p className="text-xs text-muted">Stored in PostgreSQL and used in the administrator header.</p></div>
        </div>
        {loading && <p role="status" className="mt-6 text-sm text-muted">Loading effective settings…</p>}
        {settings && <form className="mt-6 space-y-5" onSubmit={(event) => { void submit(event); }}>
          <label className="block"><span className="text-xs font-medium text-foreground">Console display name</span>
            <input value={name} maxLength={80} onChange={(event) => { setName(event.target.value); setMessage(""); }} disabled={!settings.can_edit || saving} className={inputClass} />
          </label>
          {settings.can_edit ? <>
            <label className="block"><span className="text-xs font-medium text-foreground">Change reason (recorded in audit)</span>
              <textarea rows={2} value={reason} maxLength={500} onChange={(event) => { setReason(event.target.value); setMessage(""); }} disabled={saving} placeholder="Explain why this change is required" className={inputClass} />
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <button type="submit" disabled={!canSave} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"><Save size={16} />{saving ? "Saving…" : "Save changes"}</button>
              <button type="button" disabled={saving} onClick={() => { setName(settings.display_name); setReason(""); }} className="rounded-lg border border-border px-4 py-2.5 text-sm hover:bg-background">Discard</button>
            </div>
            {name.trim() !== settings.display_name && validation && <p className="text-xs text-muted" role="status">{validation}</p>}
          </> : <p className="text-xs text-muted">Read only. A Super Admin is required to change the console name.</p>}
          <p className="text-xs text-muted">Version {settings.revision} · {settings.updated_at ? `Updated ${new Date(settings.updated_at).toLocaleString()}` : "Default value (not yet changed)"}</p>
        </form>}
      </section>
      <section className="rounded-2xl border border-border bg-surface p-5 shadow-sm sm:p-6">
        <div className="flex items-center gap-3"><span className="rounded-xl bg-blue-50 p-2.5 text-blue-600"><ShieldCheck size={18} /></span><div><h2 className="text-sm font-semibold text-foreground">Effective security & operations</h2><p className="text-xs text-muted">Read-only. Security policy cannot be changed by cosmetic UI switches.</p></div></div>
        {settings && <dl className="mt-5 divide-y divide-border text-sm">
          <div className="flex flex-wrap justify-between gap-3 py-4"><dt className="font-medium">Session cookie policy</dt><dd className="text-right text-muted">{effectiveSessionPolicy(settings.effective_security.session_cookie_age_seconds, settings.effective_security.expire_at_browser_close)}</dd></div>
          <div className="flex justify-between gap-3 py-4"><dt className="font-medium">Secure session cookie</dt><dd className="text-muted">{settings.effective_security.session_cookie_secure ? "Enabled" : "Disabled (check deployment environment)"}</dd></div>
          <div className="flex justify-between gap-3 py-4"><dt className="font-medium">Secure CSRF cookie</dt><dd className="text-muted">{settings.effective_security.csrf_cookie_secure ? "Enabled" : "Disabled (check deployment environment)"}</dd></div>
          <div className="flex justify-between gap-3 py-4"><dt className="font-medium">Admin audit logging</dt><dd className="text-muted">Enabled for instrumented admin actions; no runtime off-switch</dd></div>
          <div className="flex justify-between gap-3 py-4"><dt className="font-medium">Maintenance mode</dt><dd className="text-muted">Not implemented; no effect on access</dd></div>
        </dl>}
      </section>
      <div className="flex flex-wrap gap-5 text-sm"><Link href="/admin/audit" className="font-medium text-blue-600 hover:underline">View administrative audit</Link><Link href="/admin/infrastructure/quotas" className="font-medium text-blue-600 hover:underline">Manage storage policy and quotas</Link></div>
    </div>
  </>;
}
