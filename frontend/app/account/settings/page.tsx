import AccountPageLayout from "@/components/account/AccountPageLayout";
import EmptyState from "@/components/shared/EmptyState";

export default function SettingsPage() {
  return (
    <AccountPageLayout title="Settings" description="Account preferences and security settings.">
      <EmptyState
        title="No user settings are configured"
        description="This product currently exposes no personal settings through the account service. No inactive or cosmetic switches are shown."
      />
    </AccountPageLayout>
  );
}
