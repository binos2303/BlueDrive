import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser from "@/components/drive/DriveFileBrowser";
import CseFixtureControls from "@/components/drive/CseFixtureControls";

export default function DrivePage() {
  return (
    <DashboardShell>
      {process.env.NEXT_PUBLIC_BLUEDRIVE_CSE_FIXTURE_PIN && <CseFixtureControls />}
      <DriveFileBrowser title="My Drive" items={[]} />
    </DashboardShell>
  );
}
