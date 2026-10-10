import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser, { type DriveItem } from "@/components/drive/DriveFileBrowser";

const items: DriveItem[] = [
  { id: 1, name: "Q4 roadmap.pdf", owner: "Alex Morgan", ownerInitials: "AM", modified: "Today", size: "1.8 MB", type: "document" },
  { id: 2, name: "Brand mockups", owner: "Jamie Lee", ownerInitials: "JL", modified: "Yesterday", size: "40 MB", type: "folder" },
  { id: 3, name: "Team avatar.png", owner: "Taylor Kim", ownerInitials: "TK", modified: "Sep 22", size: "2.4 MB", type: "image" },
];

export default function SharedPage() {
  return (
    <DashboardShell>
      <DriveFileBrowser title="Shared with me" items={items} />
    </DashboardShell>
  );
}
