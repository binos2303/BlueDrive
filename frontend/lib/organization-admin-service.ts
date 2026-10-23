import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import type { OrganizationWorkspace, WorkspaceStatus } from "@/lib/workspace-service";

export type OrganizationGroup = {
  id: string;
  tenantId: string;
  name: string;
  description: string;
  status: "active" | "archived";
  memberCount: number;
  workspaceCount: number;
  createdAt: string;
  updatedAt: string;
};

export type OrganizationMember = {
  membershipId: string;
  userId: number;
  username: string;
  email: string;
  role: "owner" | "admin" | "member" | string;
  status: "active" | "invited" | "suspended" | "revoked" | string;
};

export type WorkspaceMemberAssignment = {
  assignmentId: string;
  membershipId: string;
  userId: number;
  username: string;
  email: string;
  organizationRole: string;
  workspaceRole: "admin" | "editor" | "viewer";
  status: "active" | "revoked";
};

export type GroupMemberAssignment = {
  assignmentId: string;
  membershipId: string;
  userId: number;
  username: string;
  email: string;
  organizationRole: string;
};

export type WorkspaceGroupGrant = {
  id: string;
  groupId: string;
  groupName: string;
  groupStatus: "active" | "archived";
  role: "admin" | "editor" | "viewer";
};

export type WorkspaceInput = {
  name: string;
  description: string;
  status?: WorkspaceStatus;
};

export type GroupInput = {
  name: string;
  description: string;
  status?: "active" | "archived";
};

export type WorkspacePatch = Partial<WorkspaceInput>;
export type GroupPatch = Partial<GroupInput>;

function tenantPath(tenantId: string, resourcePath = ""): string {
  return `/accounts/api/tenants/${encodeURIComponent(tenantId)}/${resourcePath}`;
}

async function mutate<T>(path: string, method: "POST" | "PATCH" | "DELETE", body?: unknown): Promise<T> {
  return requestAccountApi<T>(path, {
    method,
    headers: await accountCsrfHeaders(),
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

export async function getOrganizationAdminData(tenantId: string): Promise<{
  workspaces: OrganizationWorkspace[];
  groups: OrganizationGroup[];
  members: OrganizationMember[];
}> {
  const base = tenantPath(tenantId);
  const [workspaceResult, groupResult, memberResult] = await Promise.all([
    requestAccountApi<{ workspaces: OrganizationWorkspace[] }>(`${base}workspaces/`),
    requestAccountApi<{ groups: OrganizationGroup[] }>(`${base}groups/`),
    requestAccountApi<{ members: OrganizationMember[] }>(`${base}members/`),
  ]);
  return {
    workspaces: workspaceResult.workspaces,
    groups: groupResult.groups,
    members: memberResult.members,
  };
}

export function createWorkspace(tenantId: string, input: Pick<WorkspaceInput, "name" | "description">) {
  return mutate<{ workspace: OrganizationWorkspace }>(tenantPath(tenantId, "workspaces/"), "POST", input);
}

export function updateWorkspace(tenantId: string, workspaceId: string, input: WorkspacePatch) {
  return mutate<{ workspace: OrganizationWorkspace }>(
    tenantPath(tenantId, `workspaces/${encodeURIComponent(workspaceId)}/`),
    "PATCH",
    input,
  );
}

export function createGroup(tenantId: string, input: Pick<GroupInput, "name" | "description">) {
  return mutate<{ group: OrganizationGroup }>(tenantPath(tenantId, "groups/"), "POST", input);
}

export function updateGroup(tenantId: string, groupId: string, input: GroupPatch) {
  return mutate<{ group: OrganizationGroup }>(
    tenantPath(tenantId, `groups/${encodeURIComponent(groupId)}/`),
    "PATCH",
    input,
  );
}

export function getWorkspaceMembers(tenantId: string, workspaceId: string) {
  return requestAccountApi<{ members: WorkspaceMemberAssignment[] }>(
    tenantPath(tenantId, `workspaces/${encodeURIComponent(workspaceId)}/members/`),
  );
}

export function addWorkspaceMember(
  tenantId: string,
  workspaceId: string,
  input: { membership_id: string; role: WorkspaceMemberAssignment["workspaceRole"] },
) {
  return mutate<{ member: WorkspaceMemberAssignment }>(
    tenantPath(tenantId, `workspaces/${encodeURIComponent(workspaceId)}/members/`),
    "POST",
    input,
  );
}

export function removeWorkspaceMember(tenantId: string, workspaceId: string, membershipId: string) {
  return mutate<void>(
    tenantPath(tenantId, `workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(membershipId)}/`),
    "DELETE",
  );
}

export function getWorkspaceGroupAccess(tenantId: string, workspaceId: string) {
  return requestAccountApi<{ groupAccess: WorkspaceGroupGrant[] }>(
    tenantPath(tenantId, `workspaces/${encodeURIComponent(workspaceId)}/groups/`),
  );
}

export function grantWorkspaceGroup(
  tenantId: string,
  workspaceId: string,
  input: { group_id: string; role: WorkspaceGroupGrant["role"] },
) {
  return mutate<{ groupAccess: WorkspaceGroupGrant }>(
    tenantPath(tenantId, `workspaces/${encodeURIComponent(workspaceId)}/groups/`),
    "POST",
    input,
  );
}

export function revokeWorkspaceGroup(tenantId: string, workspaceId: string, groupId: string) {
  return mutate<void>(
    tenantPath(tenantId, `workspaces/${encodeURIComponent(workspaceId)}/groups/${encodeURIComponent(groupId)}/`),
    "DELETE",
  );
}

export function getGroupMembers(tenantId: string, groupId: string) {
  return requestAccountApi<{ members: GroupMemberAssignment[] }>(
    tenantPath(tenantId, `groups/${encodeURIComponent(groupId)}/members/`),
  );
}

export function addGroupMember(tenantId: string, groupId: string, membershipId: string) {
  return mutate<{ member: GroupMemberAssignment }>(
    tenantPath(tenantId, `groups/${encodeURIComponent(groupId)}/members/`),
    "POST",
    { membership_id: membershipId },
  );
}

export function removeGroupMember(tenantId: string, groupId: string, membershipId: string) {
  return mutate<void>(
    tenantPath(tenantId, `groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(membershipId)}/`),
    "DELETE",
  );
}
