import { ExternalLink, LifeBuoy } from "lucide-react";
import AccountPageLayout from "@/components/account/AccountPageLayout";
import { getConfiguredSupportUrl } from "@/lib/account-service";

export default function SupportPage() {
  const supportUrl = getConfiguredSupportUrl();
  return (
    <AccountPageLayout title="Support" description="Contact the configured support channel.">
      {supportUrl ? (
        <section className="rounded-2xl border border-border bg-surface p-6">
          <div className="flex items-center gap-3">
            <LifeBuoy className="text-brand-contrast" size={21} aria-hidden="true" />
            <div>
              <h2 className="font-semibold text-foreground">Support channel configured</h2>
              <p className="mt-1 text-sm text-muted">Your support channel will open in a new tab.</p>
            </div>
          </div>
          <a href={supportUrl} target="_blank" rel="noopener noreferrer" className="mt-5 inline-flex min-h-10 items-center gap-2 rounded-[var(--radius-control)] bg-brand-contrast px-4 text-sm font-semibold text-white transition-colors hover:bg-brand-dark focus-visible:outline">
            Open support <ExternalLink size={15} />
          </a>
        </section>
      ) : (
        <div role="status" className="rounded-2xl border border-amber-300 bg-amber-50 p-6 text-sm text-warning">
          Support is not connected. No request was submitted. Configure `NEXT_PUBLIC_SUPPORT_URL` or connect a backend support-request endpoint.
        </div>
      )}
    </AccountPageLayout>
  );
}
