import { notFound } from "next/navigation";
import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser from "@/components/drive/DriveFileBrowser";

export default async function WorkspaceDrivePage({ params }: {
  params: Promise<{ workspaceId: string; path: string[] }>;
}) {
  const { path } = await params;
  const [section, folderId] = path;
  const titles = new Map([["files", "Workspace files"], ["recent", "Recent"], ["starred", "Starred"], ["trash", "Trash"]]);
  const title = path.length === 1 ? titles.get(section) : undefined;
  const folder = path.length === 2 && section === "folders" && /^[1-9]\d*$/.test(folderId) && Number.isSafeInteger(Number(folderId));
  if (!title && !folder) notFound();
  return <DashboardShell><DriveFileBrowser title={title ?? "Workspace files"} items={[]} /></DashboardShell>;
}
