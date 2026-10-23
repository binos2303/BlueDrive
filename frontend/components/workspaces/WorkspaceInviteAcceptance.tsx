"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, LoaderCircle, Users } from "lucide-react";
import { useRouter } from "next/navigation";
import { useAccount } from "@/components/account/AccountProvider";
import Button from "@/components/ui/Button";
import { setActiveWorkspaceSelection, WORKSPACES_UPDATED_EVENT } from "@/lib/workspace-context";
import { acceptWorkspaceInvite, previewWorkspaceInvite } from "@/lib/workspace-service";

type InvitePreview = Awaited<ReturnType<typeof previewWorkspaceInvite>>;

export default function WorkspaceInviteAcceptance({ token }: { token: string }) {
  const router = useRouter();
  const { state: accountState } = useAccount();
  const account = accountState.status === "loaded" ? accountState.account : null;
  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [joining, setJoining] = useState(false);
  const [joined, setJoined] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!token) return;
    void previewWorkspaceInvite(token)
      .then((result) => { if (!cancelled) setPreview(result); })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "The invitation could not be verified.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [token]);

  async function handleJoin() {
    setJoining(true);
    setError(null);
    try {
      const result = await acceptWorkspaceInvite(token);
      if (account) {
        setActiveWorkspaceSelection({
          tenantId: result.workspace.tenantId,
          workspaceId: result.workspace.id,
          username: account.profile.username,
        });
      }
      window.dispatchEvent(new Event(WORKSPACES_UPDATED_EVENT));
      setJoined(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not join the workspace.");
    } finally {
      setJoining(false);
    }
  }

  const displayLoading = Boolean(token) && loading;
  const displayError = !token
    ? "This invitation link is missing its token."
    : error;

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <section className="w-full max-w-lg rounded-3xl border border-border bg-surface p-6 shadow-[var(--shadow-popover)] sm:p-8">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-soft text-brand-contrast"><Users size={22} /></div>
        {displayLoading ? (
          <div className="mt-5 flex items-center gap-2 text-sm text-muted"><LoaderCircle size={16} className="animate-spin" /> Checking invitation…</div>
        ) : joined ? (
          <>
            <CheckCircle2 size={24} className="mt-5 text-success" />
            <h1 className="mt-3 text-xl font-semibold text-foreground">You joined {preview?.workspaceName ?? "the workspace"}</h1>
            <p className="mt-2 text-sm leading-6 text-muted">The workspace is now available in your sidebar.</p>
            <Button className="mt-6 w-full" onClick={() => router.push("/drive")}>Open Drive</Button>
          </>
        ) : displayError ? (
          <>
            <h1 className="mt-5 text-xl font-semibold text-foreground">Invitation unavailable</h1>
            <p role="alert" className="mt-2 text-sm leading-6 text-danger">{displayError}</p>
            <p className="mt-3 text-sm leading-6 text-muted">Sign in with the invited email address, then reopen this link. Invitations expire after seven days.</p>
            <Link href={`/login?next=${encodeURIComponent(`/workspace-invite?token=${token}`)}`} className="mt-5 inline-flex h-10 w-full items-center justify-center rounded-xl bg-brand-contrast px-4 text-sm font-semibold text-white hover:bg-brand-dark">Sign in</Link>
          </>
        ) : preview ? (
          <>
            <h1 className="mt-5 text-xl font-semibold text-foreground">Join {preview.workspaceName}</h1>
            <p className="mt-2 text-sm leading-6 text-muted">{preview.workspaceDescription || "You have been invited to collaborate in this workspace."}</p>
            <dl className="mt-5 space-y-2 rounded-2xl border border-border bg-background p-4 text-sm">
              <div className="flex items-center justify-between gap-4"><dt className="text-muted">Invited by</dt><dd className="font-medium text-foreground">{preview.invitedBy}</dd></div>
              <div className="flex items-center justify-between gap-4"><dt className="text-muted">Invitation sent to</dt><dd className="break-all text-right font-medium text-foreground">{preview.invitedEmail}</dd></div>
              <div className="flex items-center justify-between gap-4"><dt className="text-muted">Access role</dt><dd className="font-medium capitalize text-foreground">{preview.role}</dd></div>
            </dl>
            {account ? (
              <Button className="mt-6 w-full" loading={joining} onClick={() => { void handleJoin(); }}>Accept invitation</Button>
            ) : (
              <Link href={`/login?next=${encodeURIComponent(`/workspace-invite?token=${token}`)}`} className="mt-6 inline-flex h-11 w-full items-center justify-center rounded-xl bg-brand-contrast px-4 text-sm font-semibold text-white hover:bg-brand-dark">Sign in to accept</Link>
            )}
          </>
        ) : null}
        {error && preview && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
        <Link href="/drive" className="mt-6 inline-flex text-xs font-medium text-muted hover:text-foreground">Return to Drive</Link>
      </section>
    </main>
  );
}
