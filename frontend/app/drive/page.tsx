import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser, { type DriveItem } from "@/components/drive/DriveFileBrowser";

const items: DriveItem[] = [
  { id: 1, name: "abc", owner: "Me", ownerInitials: "M", modified: "Aug 18", size: "—", type: "folder" },
  { id: 2, name: "Google AI Studio", owner: "Me", ownerInitials: "M", modified: "Apr 25", size: "—", type: "folder" },
  { id: 3, name: "Marketing assets", owner: "Me", ownerInitials: "M", modified: "Jul 8", size: "—", type: "folder" },
];

export default function DrivePage() {
  return (
    <DashboardShell>
      <DriveFileBrowser title="My Drive" items={items} />
    </DashboardShell>
  );
}
