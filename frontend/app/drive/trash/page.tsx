import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser from "@/components/drive/DriveFileBrowser";

export default function TrashPage() {
  return (
    <DashboardShell>
      <DriveFileBrowser title="Trash" items={[]} />
    </DashboardShell>
  );
}
