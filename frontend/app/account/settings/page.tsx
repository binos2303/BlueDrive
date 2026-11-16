import AccountSettingsContent from "@/components/account/AccountSettingsContent";
import { settingsTab } from "@/lib/account-settings-navigation";

export default async function SettingsPage({ searchParams }: {
  searchParams: Promise<{ section?: string | string[] }>;
}) {
  const { section } = await searchParams;
  const initialTab = settingsTab(section);
  return <AccountSettingsContent key={initialTab} initialTab={initialTab} />;
}
