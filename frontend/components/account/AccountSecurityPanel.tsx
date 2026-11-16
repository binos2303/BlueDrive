"use client";

import { useState, type FormEvent } from "react";
import Button from "@/components/ui/Button";
import { AccountServiceError } from "@/lib/account-service";
import { changeAccountPassword } from "@/lib/account-security-service";
import { passwordChangeIssue } from "@/lib/account-security-policy";

export default function AccountSecurityPanel() {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState<{ error: boolean; text: string } | null>(null);
  const [passwordFieldErrors, setPasswordFieldErrors] = useState<Record<string, string[]>>({});

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
      setOldPassword(""); setNewPassword(""); setConfirmPassword("");
      setPasswordMessage({ error: false, text: `Password changed. ${outcome.otherSessionsRevoked} other session(s) revoked. This session stays signed in.` });
    } catch (error) {
      setPasswordFieldErrors(error instanceof AccountServiceError ? error.fieldErrors : {});
      setPasswordMessage({ error: true, text: error instanceof Error ? error.message : "Password change failed." });
    } finally { setPasswordBusy(false); }
  }

  return (
      <form onSubmit={(event) => void submitPassword(event)} className="rounded-2xl border border-border bg-surface p-5 sm:p-6">
        <h2 className="text-base font-semibold text-foreground">Change password</h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">Enter your current password. Changing it signs out every other device and keeps this session active.</p>
        <div className="mt-5 grid max-w-xl gap-4">
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
        <div className="mt-5 flex"><Button type="submit" loading={passwordBusy}>Change password</Button></div>
      </form>
  );
}
