import DashboardShell from "@/components/layout/DashboardShell";
import WorkspaceActivityPage from "@/components/workspaces/WorkspaceActivityPage";

export default async function WorkspaceActivityRoute({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return (
    <DashboardShell>
      <WorkspaceActivityPage workspaceId={workspaceId} />
    </DashboardShell>
  );
}
