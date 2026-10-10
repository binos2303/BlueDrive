import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser, { type DriveItem } from "@/components/drive/DriveFileBrowser";

const items: DriveItem[] = [
  { id: 1, name: "Project plans", owner: "Me", ownerInitials: "M", modified: "Today, 9:41 AM", size: "12 MB", type: "folder" },
  { id: 2, name: "Q4 roadmap.pdf", owner: "Alex Morgan", ownerInitials: "AM", modified: "Yesterday", size: "1.8 MB", type: "document" },
  { id: 3, name: "Landing page preview.png", owner: "Me", ownerInitials: "M", modified: "Sep 12", size: "6.1 MB", type: "image" },
];

export default function RecentPage() {
  return (
    <DashboardShell>
      <DriveFileBrowser title="Recent" items={items} />
    </DashboardShell>
  );
}
