import WorkspaceInviteAcceptance from "@/components/workspaces/WorkspaceInviteAcceptance";

export default async function WorkspaceInvitePage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  return <WorkspaceInviteAcceptance token={token ?? ""} />;
}
