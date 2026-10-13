import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser from "@/components/drive/DriveFileBrowser";

export default function StarredPage() {
  return (
    <DashboardShell>
      <DriveFileBrowser title="Starred" items={[]} />
    </DashboardShell>
  );
}
