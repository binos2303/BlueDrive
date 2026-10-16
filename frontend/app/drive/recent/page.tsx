import { notFound } from "next/navigation";
import DashboardShell from "@/components/layout/DashboardShell";
import DriveFileBrowser from "@/components/drive/DriveFileBrowser";

type DriveFolderPageProps = {
  params: Promise<{
    folderId: string;
  }>;
};

export default async function DriveFolderPage({
  params,
}: DriveFolderPageProps) {
  const { folderId } = await params;

  if (!/^[1-9]\d*$/.test(folderId)) {
    notFound();
  }

  const parsedFolderId = Number(folderId);
  if (!Number.isSafeInteger(parsedFolderId)) {
    notFound();
  }

  return (
    <DashboardShell>
      <DriveFileBrowser title="My Drive" items={[]} />
    </DashboardShell>
  );
}
