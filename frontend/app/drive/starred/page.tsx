import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser, { type DriveItem } from "@/components/drive/DriveFileBrowser";

const items: DriveItem[] = [
  { id: 1, name: "Budget.xlsx", owner: "Me", ownerInitials: "M", modified: "Sep 18", size: "890 KB", type: "document" },
  { id: 2, name: "Design notes", owner: "Me", ownerInitials: "M", modified: "Sep 10", size: "7 MB", type: "folder" },
  { id: 3, name: "Client feedback.docx", owner: "Jamie Lee", ownerInitials: "JL", modified: "Sep 05", size: "540 KB", type: "document" },
];

export default function StarredPage() {
  return (
    <DashboardShell>
      <DriveFileBrowser title="Starred" items={items} />
    </DashboardShell>
  );
}
