import { redirect } from "next/navigation";
import { drivePath } from "@/lib/drive-paths";

export default async function WorkspacePage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await params;
  redirect(drivePath(workspaceId));
}
