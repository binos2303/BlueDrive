"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Cloud, Eye, EyeOff } from "lucide-react";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import { AccountServiceError, accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import { organizationInviteFragment } from "@/lib/organization-account-policy";

type Invitation = NonNullable<ReturnType<typeof organizationInviteFragment>>;

export default function OrganizationInvitePage() {
  const consumed = useRef(false);
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const [ready, setReady] = useState(false);
  const [password1, setPassword1] = useState("");
  const [password2, setPassword2] = useState("");
  const [visible, setVisible] = useState(false);
  const [pending, setPending] = useState(false);
  const [activated, setActivated] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const submitting = useRef(false);

  useEffect(() => {
    if (consumed.current) return;
    consumed.current = true;
    const value = organizationInviteFragment(window.location.hash);
    // Xóa fragment trước mọi request; token chỉ sống trong memory của trang này.
    window.history.replaceState(null, "", "/organization-invite");
    void Promise.resolve().then(() => { setInvitation(value); setReady(true); });
  }, []);

  async function activate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!invitation || submitting.current || password1 !== password2) return;
    submitting.current = true; setPending(true); setError(""); setFieldErrors({});
    try {
      const result = await requestAccountApi<{ activated: boolean }>("/accounts/api/organization-invite/accept/", {
        method: "POST", headers: await accountCsrfHeaders(),
        body: JSON.stringify({ ...invitation, password1, password2 }),
      });
      if (!result.activated) throw new Error("The account was not activated. Ask for a new invitation.");
      setActivated(true); setInvitation(null); setPassword1(""); setPassword2("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Activation failed. Retry or ask for a new invitation.");
      if (cause instanceof AccountServiceError) setFieldErrors(cause.fieldErrors);
    } finally { submitting.current = false; setPending(false); }
  }

  return <main className="flex min-h-screen items-center justify-center bg-background px-5 py-12">
    <section className="w-full max-w-[500px] rounded-3xl border border-border bg-surface p-7 shadow-[var(--shadow-popover)] sm:p-10">
      <div className="mb-6 flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand text-on-accent"><Cloud size={20} /></span><span className="font-semibold">BlueDrive</span></div>
      <h1 className="text-2xl font-semibold">Activate your organization account</h1>
      {!ready ? <p role="status" className="mt-5 text-sm text-muted">Loading invitation…</p> : activated ? <div className="mt-6 space-y-4">
        <p role="status" className="text-sm text-success">Your account is activated. Sign in to access your organization My Drive.</p>
        <Link href="/login?next=%2Fdrive" className="inline-flex min-h-11 items-center rounded-xl bg-brand-contrast px-4 text-sm font-semibold text-on-accent">Sign in</Link>
      </div> : !invitation ? <div className="mt-5 space-y-3"><p role="alert" className="text-sm text-danger">This invitation is missing or incomplete.</p><p className="text-sm text-muted">Open the original invitation email or ask your organization administrator for a new invitation.</p></div> :
      <form className="mt-6 space-y-4" onSubmit={(event) => void activate(event)}>
        <p className="text-sm leading-6 text-muted">Your My Drive belongs to your organization. Choose a unique password with at least 12 characters to activate your account.</p>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <div><label htmlFor="activation-password" className="block text-sm font-medium">New password</label><div className="relative mt-1"><Input id="activation-password" required minLength={12} type={visible ? "text" : "password"} autoComplete="new-password" disabled={pending} value={password1} invalid={Boolean(fieldErrors.password1)} aria-describedby={fieldErrors.password1 ? "activation-password-error" : undefined} onChange={(event) => setPassword1(event.target.value)} className="pr-12" />
          <button type="button" aria-label={visible ? "Hide passwords" : "Show passwords"} onClick={() => setVisible(!visible)} className="ui-control absolute right-1 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-lg text-muted">{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>
          {fieldErrors.password1 && <p id="activation-password-error" className="mt-1 text-xs text-danger">{fieldErrors.password1.join(" ")}</p>}
        </div>
        <div><label htmlFor="activation-confirmation" className="block text-sm font-medium">Confirm password</label><Input id="activation-confirmation" required minLength={12} type={visible ? "text" : "password"} autoComplete="new-password" disabled={pending} value={password2} invalid={Boolean(fieldErrors.password2)} aria-describedby={fieldErrors.password2 ? "activation-confirmation-error" : undefined} onChange={(event) => setPassword2(event.target.value)} className="mt-1" />
          {fieldErrors.password2 && <p id="activation-confirmation-error" className="mt-1 text-xs text-danger">{fieldErrors.password2.join(" ")}</p>}
        </div>
        {password2 && password1 !== password2 && <p role="alert" className="text-xs text-danger">Passwords do not match.</p>}
        <Button type="submit" className="w-full" loading={pending} disabled={password1.length < 12 || password1 !== password2}>Activate account</Button>
      </form>}
    </section>
  </main>;
}
