"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Cloud, Eye, EyeOff } from "lucide-react";
import Button from "@/components/ui/Button";
import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import { organizationInviteFragment } from "@/lib/organization-account-policy";

function AdminInviteContent() {
  const consumed = useRef(false);
  const submitting = useRef(false);
  const [invitation, setInvitation] = useState<ReturnType<typeof organizationInviteFragment>>(null);
  const [ready, setReady] = useState(false);
  const [password1, setPassword1] = useState("");
  const [password2, setPassword2] = useState("");
  const [visible, setVisible] = useState(false);
  const [pending, setPending] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (consumed.current) return;
    consumed.current = true;
    const value = organizationInviteFragment(window.location.hash, window.location.search);
    // Xóa cả query của link cũ trước mọi request; không lưu token để đăng nhập lại.
    window.history.replaceState(null, "", "/admin-invite");
    void Promise.resolve().then(() => { setInvitation(value); setReady(true); });
  }, []);

  async function activate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError("");
    if (submitting.current) return;
    if (!invitation || password1 !== password2) { setError("Invalid invitation or passwords do not match."); return; }
    submitting.current = true; setPending(true);
    try {
      const headers = await accountCsrfHeaders();
      await requestAccountApi("/accounts/api/admin-invite/accept/", {
        method: "POST", headers, body: JSON.stringify({ ...invitation, password1, password2 }),
      });
      setSuccess(true); setInvitation(null); setPassword1(""); setPassword2("");
    } catch (cause: unknown) { setError(cause instanceof Error ? cause.message : "Activation failed."); }
    finally { submitting.current = false; setPending(false); }
  }

  return <main className="flex min-h-screen items-center justify-center bg-background px-5 py-12">
    <section className="w-full max-w-[500px] rounded-3xl border border-border bg-surface p-7 shadow-[var(--shadow-popover)] sm:p-10">
      <div className="mb-6 flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand text-on-accent"><Cloud size={20}/></span><span className="font-semibold">BlueDrive</span></div>
      <p className="text-xs font-semibold uppercase tracking-wider text-brand-contrast">Platform Administration</p>
      <h1 className="mt-2 text-2xl font-semibold">Activate your administrator account</h1>
      {!ready ? <p role="status" className="mt-6 text-sm text-muted">Loading invitation…</p> : success ? <div className="mt-6 space-y-4"><p role="status" className="text-sm text-success">Your account has been activated. Sign in to continue.</p><Link className="inline-block rounded-xl bg-brand-contrast px-4 py-3 text-sm font-semibold text-on-accent" href="/login?next=%2Fadmin">Sign in</Link></div> :
      <form onSubmit={(event) => void activate(event)} className="mt-6 space-y-4">
        <p className="text-[13px] leading-6 text-muted">This invitation creates an administrator-only account. Choose a unique password with at least 12 characters. This account has no My Drive.</p>
        <div><label htmlFor="admin-invite-password" className="block text-[13px] font-semibold">New password</label><div className="relative mt-2"><input id="admin-invite-password" required minLength={12} value={password1} type={visible ? "text" : "password"} autoComplete="new-password" onChange={(event) => setPassword1(event.target.value)} className="h-11 w-full rounded-xl border border-border bg-background px-3 pr-12 text-sm"/><button type="button" aria-label={visible ? "Hide passwords" : "Show passwords"} className="ui-control absolute right-1 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-lg text-muted" onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18}/> : <Eye size={18}/>}</button></div></div>
        <div><label htmlFor="admin-invite-confirmation" className="block text-[13px] font-semibold">Confirm password</label><input id="admin-invite-confirmation" required minLength={12} value={password2} type={visible ? "text" : "password"} autoComplete="new-password" onChange={(event) => setPassword2(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-border bg-background px-3 text-sm"/></div>
        {!invitation ? <p role="alert" className="text-xs text-danger">The invitation link is missing or incomplete.</p> : null}
        {error && <p role="alert" className="text-xs text-danger">{error}</p>}
        <Button type="submit" loading={pending} className="w-full" disabled={!invitation || !password1 || password1 !== password2}>Activate administrator account</Button>
      </form>}
    </section>
  </main>;
}


export default function AdminInvitePage() {
  return <AdminInviteContent />;
}
