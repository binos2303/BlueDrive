import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser, { type DriveItem } from "@/components/drive/DriveFileBrowser";

const items: DriveItem[] = [
  { id: 1, name: "Old campaign assets", owner: "Me", ownerInitials: "M", modified: "Sep 02", size: "18 MB", type: "folder" },
  { id: 2, name: "Draft proposal.docx", owner: "Me", ownerInitials: "M", modified: "Aug 28", size: "620 KB", type: "document" },
];

export default function TrashPage() {
  return (
    <DashboardShell>
      <DriveFileBrowser title="Trash" items={items} />
    </DashboardShell>
  );
}
