"use client";

import { useState, type FormEvent } from "react";
import Button from "@/components/ui/Button";
import AccountPageLayout from "@/components/account/AccountPageLayout";
import { useAccount } from "@/components/account/AccountProvider";
import { AccountServiceError, type AccountSnapshot } from "@/lib/account-service";

export default function ProfilePage() {
  const { state, refresh, updateProfile } = useAccount();

  return (
    <AccountPageLayout title="Profile" description="Review account information supplied by the account service.">
      {state.status === "loading" && (
        <div role="status" aria-live="polite" className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
          Loading profile…
        </div>
      )}
      {state.status === "error" && (
        <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-6">
          <h2 className="font-semibold text-danger">Profile unavailable</h2>
          <p className="mt-2 text-sm text-danger">{state.error}</p>
          <Button className="mt-4" variant="secondary" onClick={() => void refresh()}>Retry</Button>
        </div>
      )}
      {state.status === "loaded" && (
        <ProfileForm
          key={state.account.profile.username}
          account={state.account}
          updateProfile={updateProfile}
        />
      )}
    </AccountPageLayout>
  );
}

function ProfileForm({
  account,
  updateProfile,
}: {
  account: AccountSnapshot;
  updateProfile: (input: { email: string }) => Promise<AccountSnapshot>;
}) {
  const [email, setEmail] = useState(account.profile.email);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFieldError(null);
    setSaveError(null);
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setFieldError("Enter a valid email address.");
      setSaveState("error");
      return;
    }

    setSaveState("saving");
    try {
      const updated = await updateProfile({ email: email.trim() });
      setEmail(updated.profile.email);
      setSaveState("saved");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Profile could not be saved.";
      setSaveError(message);
      setFieldError(error instanceof AccountServiceError ? error.fieldErrors.email?.[0] ?? null : null);
      setSaveState("error");
    }
  }

  return (
    <div className="space-y-5">
          {account.account.type === "unclassified" && (
            <div role="status" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-warning">
              Account type has not been classified by the backend. No plan or tenant privileges are inferred.
            </div>
          )}
          {account.account.type === "business" && account.account.tenant && (
            <div className="rounded-xl border border-border bg-surface p-4 text-sm">
              <p className="font-medium text-foreground">{account.account.tenant.name}</p>
              <p className="mt-1 text-muted">Business account · {account.account.tenant.role}</p>
              <p className="mt-2 text-muted">Storage quota for business members is allocated by the Tenant Admin.</p>
            </div>
          )}
          <form onSubmit={(event) => void handleSubmit(event)} className="space-y-5 rounded-2xl border border-border bg-surface p-5 sm:p-7">
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-foreground">Username</span>
              <input
                value={account.profile.username}
                readOnly
                className="h-11 w-full rounded-xl border border-border bg-background px-3 text-sm text-muted"
              />
              <span className="mt-1 block text-xs text-muted">This account field is read-only.</span>
            </label>
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-foreground">Email</span>
              <input
                type="email"
                autoComplete="email"
                required
                maxLength={254}
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  setSaveState("idle");
                  setFieldError(null);
                }}
                aria-invalid={Boolean(fieldError)}
                aria-describedby={fieldError ? "profile-email-error" : undefined}
                className="h-11 w-full rounded-xl border border-border bg-background px-3 text-sm text-foreground focus:border-brand-contrast"
              />
              {fieldError && <span id="profile-email-error" className="mt-1 block text-sm text-danger">{fieldError}</span>}
            </label>
            {saveState === "saved" && <p role="status" aria-live="polite" className="text-sm text-success">Profile saved.</p>}
            {saveState === "error" && saveError && <p role="alert" className="text-sm text-danger">{saveError}</p>}
            <div className="flex justify-end border-t border-border pt-4">
              <Button type="submit" disabled={saveState === "saving" || email.trim() === account.profile.email}>
                {saveState === "saving" ? "Saving…" : "Save changes"}
              </Button>
            </div>
          </form>
    </div>
  );
}
