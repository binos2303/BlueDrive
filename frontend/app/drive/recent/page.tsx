import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser from "@/components/drive/DriveFileBrowser";

export default function RecentPage() {
  return (
    <DashboardShell>
      <DriveFileBrowser title="Recent" items={[]} />
    </DashboardShell>
  );
}
