import DashboardShell from "@/components/layout/DashboardShell";
import WorkspaceMembersPage from "@/components/workspaces/WorkspaceMembersPage";

export default async function WorkspaceMembersRoute({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return (
    <DashboardShell>
      <WorkspaceMembersPage workspaceId={workspaceId} />
    </DashboardShell>
  );
}
