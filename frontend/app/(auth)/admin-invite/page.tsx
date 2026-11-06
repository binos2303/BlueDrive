"use client";

import Link from "next/link";
import { Suspense, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { Cloud, Eye, EyeOff } from "lucide-react";
import Button from "@/components/ui/Button";
import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";

function AdminInviteContent() {
  const searchParams = useSearchParams();
  const uid = searchParams.get("uid") ?? "";
  const token = searchParams.get("token") ?? "";
  const [password1, setPassword1] = useState("");
  const [password2, setPassword2] = useState("");
  const [visible, setVisible] = useState(false);
  const [pending, setPending] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  async function activate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError("");
    if (!uid || !token || password1 !== password2) { setError("Invalid invitation or passwords do not match."); return; }
    setPending(true);
    try {
      const headers = await accountCsrfHeaders();
      await requestAccountApi("/accounts/api/admin-invite/accept/", {
        method: "POST", headers, body: JSON.stringify({ uid, token, password1, password2 }),
      });
      setSuccess(true); setPassword1(""); setPassword2("");
      window.history.replaceState(null, "", "/admin-invite");
    } catch (cause: unknown) { setError(cause instanceof Error ? cause.message : "Activation failed."); }
    finally { setPending(false); }
  }

  return <main className="flex min-h-screen items-center justify-center bg-background px-5 py-12">
    <section className="w-full max-w-[500px] rounded-3xl border border-border bg-surface p-7 shadow-[var(--shadow-popover)] sm:p-10">
      <div className="mb-6 flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand text-white"><Cloud size={20}/></span><span className="font-semibold">BlueDrive</span></div>
      <p className="text-xs font-semibold uppercase tracking-wider text-brand-contrast">Platform Administration</p>
      <h1 className="mt-2 text-2xl font-semibold">Activate your administrator account</h1>
      {success ? <div className="mt-6 space-y-4"><p className="text-sm text-success">Your account has been activated. Sign in to continue.</p><Link className="inline-block rounded-xl bg-brand-contrast px-4 py-3 text-sm font-semibold text-white" href="/login?next=%2Fadmin">Sign in</Link></div> :
      <form onSubmit={(event) => void activate(event)} className="mt-6 space-y-4">
        <p className="text-[13px] leading-6 text-muted">This invitation creates an administrator-only account. Choose a unique, strong password. This account has no My Drive.</p>
        <label className="block text-[13px] font-semibold">New password<div className="relative mt-2"><input required minLength={12} value={password1} type={visible ? "text" : "password"} autoComplete="new-password" onChange={(event) => setPassword1(event.target.value)} className="h-11 w-full rounded-xl border border-border bg-background px-3 pr-12 text-sm"/><button type="button" aria-label={visible ? "Hide passwords" : "Show passwords"} className="absolute right-3 top-3 text-muted" onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18}/> : <Eye size={18}/>}</button></div></label>
        <label className="block text-[13px] font-semibold">Confirm password<input required minLength={12} value={password2} type={visible ? "text" : "password"} autoComplete="new-password" onChange={(event) => setPassword2(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-border bg-background px-3 text-sm"/></label>
        {!uid || !token ? <p role="alert" className="text-xs text-danger">The invitation link is missing or incomplete.</p> : null}
        {error && <p role="alert" className="text-xs text-danger">{error}</p>}
        <Button type="submit" loading={pending} className="w-full" disabled={!uid || !token || !password1 || password1 !== password2}>Activate administrator account</Button>
      </form>}
    </section>
  </main>;
}


export default function AdminInvitePage() {
  return (
    <Suspense fallback={<main className="flex min-h-screen items-center justify-center">Loading invitation…</main>}>
      <AdminInviteContent />
    </Suspense>
  );
}
