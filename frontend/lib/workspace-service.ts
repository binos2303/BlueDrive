import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";

export type WorkspaceStatus = "active" | "archived";
export type WorkspaceRole = "viewer" | "editor" | "admin";
export type InviteRole = "viewer" | "editor";

export type OrganizationWorkspace = {
  id: string;
  tenantId: string;
  tenantName: string;
  tenantKind: "personal" | "business";
  name: string;
  slug: string;
  description: string;
  status: WorkspaceStatus;
  isDefault: boolean;
  defaultMemberRole: InviteRole;
  currentUserRole: WorkspaceRole | null;
  canManage: boolean;
  createdByUserId: number | null;
  createdByUsername: string;
  createdByInitials: string;
  isOwnedByMe: boolean;
  memberCount: number;
  groupCount: number;
  createdAt: string;
  updatedAt: string;
};

export type CreateWorkspaceInput = {
  name: string;
  description: string;
  default_member_role: InviteRole;
};

export type WorkspaceInviteResult = {
  invitationId: string;
  email: string;
  role: InviteRole;
  workspaceId: string;
  workspaceName: string;
  inviteToken: string;
  expiresAt: string;
};

export type WorkspaceActivityEvent = {
  id: number;
  username: string;
  action: string;
  actionLabel: string;
  description: string;
  createdAt: string;
  metadata: Record<string, unknown>;
};

export async function getMyWorkspaces(): Promise<OrganizationWorkspace[]> {
  const result = await requestAccountApi<{ workspaces: OrganizationWorkspace[] }>(
    "/accounts/api/workspaces/",
  );
  return result.workspaces;
}

export async function createMyWorkspace(input: CreateWorkspaceInput): Promise<OrganizationWorkspace> {
  const result = await requestAccountApi<{ workspace: OrganizationWorkspace }>(
    "/accounts/api/workspaces/",
    {
      method: "POST",
      headers: await accountCsrfHeaders(),
      body: JSON.stringify(input),
    },
  );
  return result.workspace;
}

export async function updateWorkspace(
  workspaceId: string,
  input: Partial<Pick<OrganizationWorkspace, "name" | "description" | "status" | "defaultMemberRole">>,
): Promise<OrganizationWorkspace> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name;
  if (input.description !== undefined) body.description = input.description;
  if (input.status !== undefined) body.status = input.status;
  if (input.defaultMemberRole !== undefined) body.default_member_role = input.defaultMemberRole;
  const result = await requestAccountApi<{ workspace: OrganizationWorkspace }>(
    `/accounts/api/workspaces/${encodeURIComponent(workspaceId)}/`,
    { method: "PATCH", headers: await accountCsrfHeaders(), body: JSON.stringify(body) },
  );
  return result.workspace;
}

export async function createWorkspaceInvite(
  workspaceId: string,
  input: { email: string; role: InviteRole },
): Promise<WorkspaceInviteResult> {
  return requestAccountApi<WorkspaceInviteResult>(
    `/accounts/api/workspaces/${encodeURIComponent(workspaceId)}/invites/`,
    {
      method: "POST",
      headers: await accountCsrfHeaders(),
      body: JSON.stringify(input),
    },
  );
}

export async function previewWorkspaceInvite(token: string): Promise<{
  workspaceId: string;
  workspaceName: string;
  workspaceDescription: string;
  invitedEmail: string;
  role: InviteRole;
  invitedBy: string;
  expiresAt: string;
}> {
  const params = new URLSearchParams({ token });
  return requestAccountApi(`/accounts/api/workspace-invites/preview/?${params.toString()}`);
}

export async function acceptWorkspaceInvite(token: string): Promise<{
  joined: boolean;
  alreadyMember: boolean;
  workspace: OrganizationWorkspace;
}> {
  return requestAccountApi("/accounts/api/workspace-invites/accept/", {
    method: "POST",
    headers: await accountCsrfHeaders(),
    body: JSON.stringify({ token }),
  });
}

export async function getWorkspaceActivity(workspaceId: string): Promise<WorkspaceActivityEvent[]> {
  const result = await requestAccountApi<{ events: WorkspaceActivityEvent[] }>(
    `/accounts/api/workspaces/${encodeURIComponent(workspaceId)}/activity/`,
  );
  return result.events;
}
