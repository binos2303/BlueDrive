"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Button from "@/components/ui/Button";
import { AccountServiceError } from "@/lib/account-service";
import {
  changeAccountPassword, getAccountSessions, revokeAccountSession,
  revokeOtherAccountSessions, type AccountSessionsPage,
} from "@/lib/account-security-service";
import { mayHaveNextPage, passwordChangeIssue } from "@/lib/account-security-policy";

function formatDate(value: string): string {
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? "Unavailable" : new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short",
  }).format(timestamp);
}

export default function AccountSecurityPanel() {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState<{ error: boolean; text: string } | null>(null);
  const [passwordFieldErrors, setPasswordFieldErrors] = useState<Record<string, string[]>>({});
  const [sessionPassword, setSessionPassword] = useState("");
  const [sessionsPage, setSessionsPage] = useState<AccountSessionsPage | null>(null);
  const [page, setPage] = useState(1);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsBusy, setSessionsBusy] = useState(false);
  const [sessionsMessage, setSessionsMessage] = useState<{ error: boolean; text: string } | null>(null);

  const loadSessions = useCallback(async (requestedPage: number) => {
    try {
      const result = await getAccountSessions(requestedPage);
      setSessionsPage(result);
      setPage(result.page);
      setSessionsMessage(null);
    } catch (error) {
      setSessionsPage(null);
      setSessionsMessage({ error: true, text: error instanceof Error ? error.message : "Could not load sessions." });
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    // Subscribe to the initial asynchronous session load without setting state
    // synchronously from an effect or applying results after unmount.
    let active = true;
    getAccountSessions(1)
      .then((result) => {
        if (!active) return;
        setSessionsPage(result);
        setPage(result.page);
        setSessionsMessage(null);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setSessionsPage(null);
        setSessionsMessage({
          error: true,
          text: error instanceof Error ? error.message : "Could not load sessions.",
        });
      })
      .finally(() => {
        if (active) setSessionsLoading(false);
      });
    return () => { active = false; };
  }, []);

  function refreshSessions(requestedPage: number) {
    setSessionsLoading(true);
    void loadSessions(requestedPage);
  }

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPasswordMessage(null);
    setPasswordFieldErrors({});
    const issue = passwordChangeIssue(oldPassword, newPassword, confirmPassword);
    if (issue) { setPasswordMessage({ error: true, text: issue }); return; }
    setPasswordBusy(true);
    try {
      const outcome = await changeAccountPassword({
        old_password: oldPassword, new_password1: newPassword, new_password2: confirmPassword,
      });
      setOldPassword(""); setNewPassword(""); setConfirmPassword(""); setSessionPassword("");
      setPasswordMessage({ error: false, text: `Password changed. ${outcome.otherSessionsRevoked} other session(s) revoked. This session stays signed in.` });
      await loadSessions(1);
    } catch (error) {
      setPasswordFieldErrors(error instanceof AccountServiceError ? error.fieldErrors : {});
      setPasswordMessage({ error: true, text: error instanceof Error ? error.message : "Password change failed." });
    } finally { setPasswordBusy(false); }
  }

  async function revokeSession(id: string, current: boolean) {
    if (!sessionPassword) { setSessionsMessage({ error: true, text: "Enter your current password to revoke sessions." }); return; }
    if (!window.confirm(current ? "Sign out of this device?" : "Revoke this device session?")) return;
    setSessionsBusy(true);
    setSessionsMessage(null);
    try {
      const result = await revokeAccountSession(id, sessionPassword);
      setSessionPassword("");
      if (result.signedOut) { window.location.replace("/login?loggedOut=1"); return; }
      await loadSessions(page);
      setSessionsMessage({ error: false, text: "Session revoked." });
    } catch (error) {
      setSessionsMessage({ error: true, text: error instanceof Error ? error.message : "Could not revoke session." });
    } finally { setSessionsBusy(false); }
  }

  async function revokeOthers() {
    if (!sessionPassword) { setSessionsMessage({ error: true, text: "Enter your current password to revoke sessions." }); return; }
    if (!window.confirm("Sign out of every other session, including older unlisted sessions?")) return;
    setSessionsBusy(true);
    setSessionsMessage(null);
    try {
      const result = await revokeOtherAccountSessions(sessionPassword);
      setSessionPassword("");
      await loadSessions(1);
      setSessionsMessage({ error: false, text: `${result.revoked} other session(s) revoked.` });
    } catch (error) {
      setSessionsMessage({ error: true, text: error instanceof Error ? error.message : "Could not revoke other sessions." });
    } finally { setSessionsBusy(false); }
  }

  return (
    <div className="space-y-5">
      <form onSubmit={(event) => void submitPassword(event)} className="rounded-2xl border border-border bg-surface p-5 sm:p-7">
        <h2 className="text-base font-semibold text-foreground">Change password</h2>
        <p className="mt-1 text-sm text-muted">Enter your current password. Changing it signs out every other device and keeps this session active.</p>
        <div className="mt-5 grid gap-4">
          {([
            { label: "Current password", value: oldPassword, setter: setOldPassword, field: "old_password", autoComplete: "current-password" },
            { label: "New password", value: newPassword, setter: setNewPassword, field: "new_password1", autoComplete: "new-password" },
            { label: "Confirm new password", value: confirmPassword, setter: setConfirmPassword, field: "new_password2", autoComplete: "new-password" },
          ] as const).map((field) => (
            <label key={field.field} className="block">
              <span className="mb-1.5 block text-sm font-medium text-foreground">{field.label}</span>
              <input type="password" autoComplete={field.autoComplete} maxLength={4096} required
                value={field.value} onChange={(event) => { field.setter(event.currentTarget.value); setPasswordMessage(null); }}
                className="h-11 w-full rounded-xl border border-border bg-background px-3 text-sm text-foreground focus:border-brand-contrast" />
              {passwordFieldErrors[field.field]?.map((message) => <span key={message} className="mt-1 block text-xs text-danger">{message}</span>)}
            </label>
          ))}
        </div>
        {passwordMessage && <p role={passwordMessage.error ? "alert" : "status"} className={`mt-4 text-sm ${passwordMessage.error ? "text-danger" : "text-success"}`}>{passwordMessage.text}</p>}
        <div className="mt-5 flex justify-end"><Button type="submit" loading={passwordBusy}>Change password</Button></div>
      </form>

      <section className="rounded-2xl border border-border bg-surface p-5 sm:p-7">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h2 className="text-base font-semibold text-foreground">Active sessions</h2>
            <p className="mt-1 max-w-2xl text-sm text-muted">Sessions observed since tracking was enabled. An unexpired session is not proof a device is online.</p></div>
          <Button variant="secondary" size="sm" onClick={() => refreshSessions(page)} disabled={sessionsLoading || sessionsBusy}>Refresh</Button>
        </div>
        <label className="mt-5 block max-w-md">
          <span className="mb-1.5 block text-sm font-medium text-foreground">Current password to revoke sessions</span>
          <input type="password" autoComplete="current-password" maxLength={4096} value={sessionPassword}
            onChange={(event) => setSessionPassword(event.currentTarget.value)}
            className="h-11 w-full rounded-xl border border-border bg-background px-3 text-sm text-foreground focus:border-brand-contrast" />
        </label>
        <div className="mt-3"><Button variant="secondary" disabled={sessionsBusy || sessionsLoading || !sessionPassword}
          onClick={() => void revokeOthers()} loading={sessionsBusy}>Sign out of other devices</Button></div>
        {sessionsMessage && <p role={sessionsMessage.error ? "alert" : "status"} className={`mt-3 text-sm ${sessionsMessage.error ? "text-danger" : "text-success"}`}>{sessionsMessage.text}</p>}
        {sessionsLoading ? <p role="status" className="mt-5 text-sm text-muted">Loading sessions…</p> : (
          <div className="mt-5 divide-y divide-border rounded-xl border border-border">
            {(sessionsPage?.sessions ?? []).length === 0 && <p className="p-4 text-sm text-muted">No tracked sessions found.</p>}
            {(sessionsPage?.sessions ?? []).map((session) => (
              <div key={session.id} className="flex flex-wrap items-center justify-between gap-4 p-4">
                <div className="min-w-0 text-sm">
                  <p className="font-medium text-foreground">{session.current ? "Current session" : "Other session"}</p>
                  <p className="mt-1 break-all text-xs text-muted">{session.userAgent || "Device not identified"}</p>
                  <p className="mt-1 text-xs text-muted">Last observed: {formatDate(session.lastSeenAt)} · Expires: {formatDate(session.expiresAt)}</p>
                </div>
                <Button variant={session.current ? "secondary" : "destructive"} size="sm"
                  disabled={sessionsBusy || !sessionPassword} onClick={() => void revokeSession(session.id, session.current)}>
                  {session.current ? "Sign out here" : "Revoke"}
                </Button>
              </div>
            ))}
          </div>
        )}
        <div className="mt-4 flex items-center justify-between gap-3 text-xs text-muted">
          <span>{sessionsPage?.count ?? 0} observed session(s)</span>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" disabled={sessionsBusy || sessionsLoading || page <= 1} onClick={() => refreshSessions(page - 1)}>Previous</Button>
            <Button variant="secondary" size="sm" disabled={sessionsBusy || sessionsLoading || !mayHaveNextPage(sessionsPage?.count ?? 0, page, sessionsPage?.pageSize ?? 20)} onClick={() => refreshSessions(page + 1)}>Next</Button>
          </div>
        </div>
      </section>
    </div>
  );
}
