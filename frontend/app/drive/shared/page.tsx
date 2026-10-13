import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser from "@/components/drive/DriveFileBrowser";

export default function SharedPage() {
  return (
    <DashboardShell>
      <DriveFileBrowser title="Shared with me" items={[]} />
    </DashboardShell>
  );
}
