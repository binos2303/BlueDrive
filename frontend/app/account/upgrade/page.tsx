"use client";

import { useState } from "react";
import AccountPageLayout from "@/components/account/AccountPageLayout";
import Button from "@/components/ui/Button";
import { useAccount } from "@/components/account/AccountProvider";

export default function UpgradePage() {
  const { state, refresh, requestUpgrade, actionError, clearActionError } = useAccount();
  const [requestState, setRequestState] = useState<"idle" | "saving">("idle");

  async function submitUpgradeRequest() {
    setRequestState("saving");
    try {
      await requestUpgrade();
    } catch {
      // The provider exposes an explicit error and does not report success.
    } finally {
      setRequestState("idle");
    }
  }

  return (
    <AccountPageLayout title="Upgrade plan" description="Plan eligibility is determined by the backend account and tenant records.">
      {state.status === "loading" && (
        <p role="status" className="rounded-xl border border-border bg-surface p-5 text-sm text-muted">Checking account eligibility…</p>
      )}
      {state.status === "error" && (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-5">
          <p className="text-sm text-danger">{state.error}</p>
          <Button className="mt-4" variant="secondary" onClick={() => void refresh()}>Retry</Button>
        </div>
      )}
      {state.status === "loaded" && state.account.account.type === "business" && (
        <div role="status" className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
          Personal plan upgrades are not available for business members. Contact your Tenant Admin about account access and quota allocation.
        </div>
      )}
      {state.status === "loaded" && state.account.account.type === "unclassified" && (
        <div role="status" className="rounded-2xl border border-amber-300 bg-amber-50 p-6 text-sm text-warning">
          Upgrade eligibility cannot be verified because the backend has not classified this account. No upgrade action is available.
        </div>
      )}
      {state.status === "loaded" && state.account.account.type === "individual" && state.account.account.upgradeEligible !== true && (
        <div role="status" className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
          The backend has not marked this individual account as eligible for an upgrade.
        </div>
      )}
      {state.status === "loaded" && state.account.account.type === "individual" && state.account.account.upgradeEligible === true && (
        <section className="rounded-2xl border border-border bg-surface p-6">
          <h2 className="font-semibold text-foreground">Upgrade is available for this individual account</h2>
          <p className="mt-2 text-sm text-muted">The backend must re-check account eligibility and authorize any plan change.</p>
          {actionError && <p role="alert" className="mt-3 text-sm text-danger">{actionError}</p>}
          <Button className="mt-5" disabled={requestState === "saving"} onClick={() => void submitUpgradeRequest()}>
            {requestState === "saving" ? "Submitting…" : "Continue to upgrade"}
          </Button>
          {actionError && <button type="button" onClick={clearActionError} className="ml-3 text-sm text-muted underline">Dismiss</button>}
        </section>
      )}
    </AccountPageLayout>
  );
}
