import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser from "@/components/drive/DriveFileBrowser";

export default function DrivePage() {
  return (
    <DashboardShell>
      <DriveFileBrowser title="My Drive" items={[]} />
    </DashboardShell>
  );
}
