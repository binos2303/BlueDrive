"use client";

import AccountPageLayout from "@/components/account/AccountPageLayout";
import Button from "@/components/ui/Button";
import { useAccount } from "@/components/account/AccountProvider";

export default function UpgradePage() {
  const { state, refresh } = useAccount();

  return (
    <AccountPageLayout title="Plan details" description="View plan availability for your account.">
      {state.status === "loading" && (
        <p role="status" className="rounded-xl border border-border bg-surface p-5 text-sm text-muted">Checking account eligibility…</p>
      )}
      {state.status === "error" && (
        <div role="alert" className="rounded-xl border border-danger/30 bg-danger-soft p-5">
          <p className="text-sm text-danger">{state.error}</p>
          <Button className="mt-4" variant="secondary" onClick={() => void refresh()}>Retry</Button>
        </div>
      )}
      {state.status === "loaded" && state.account.account.type === "business" && (
        <div role="status" className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
          Personal plan upgrades are not available for business members. Contact your organization administrator about account access and quota allocation.
        </div>
      )}
      {state.status === "loaded" && state.account.account.type === "unclassified" && (
        <div role="status" className="rounded-2xl border border-warning/30 bg-warning-soft p-6 text-sm text-warning">
          Your account type has not been confirmed, so plan eligibility cannot be checked.
        </div>
      )}
      {state.status === "loaded" && state.account.account.type === "individual" && state.account.account.upgradeEligible !== true && (
        <div role="status" className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
          A plan upgrade is not available for this account.
        </div>
      )}
      {state.status === "loaded" && state.account.account.type === "individual" && state.account.account.upgradeEligible === true && (
        <section className="rounded-2xl border border-border bg-surface p-6">
          <h2 className="font-semibold text-foreground">Plan upgrades are not available yet</h2>
          <p className="mt-2 text-sm text-muted">An upgrade cannot be completed at this time.</p>
        </section>
      )}
    </AccountPageLayout>
  );
}
