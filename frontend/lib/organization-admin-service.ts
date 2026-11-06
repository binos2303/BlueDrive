import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import type { OrganizationWorkspace, WorkspaceStatus } from "@/lib/workspace-service";

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

export type WorkspaceInput = {
  name: string;
  description: string;
  status?: WorkspaceStatus;
};

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

/** Get only organization workspaces and members; access is assigned per user. */
export async function getOrganizationAdminData(tenantId: string): Promise<{
  workspaces: OrganizationWorkspace[];
  members: OrganizationMember[];
}> {
  const base = tenantPath(tenantId);
  const [workspaceResult, memberResult] = await Promise.all([
    requestAccountApi<{ workspaces: OrganizationWorkspace[] }>(`${base}workspaces/`),
    requestAccountApi<{ members: OrganizationMember[] }>(`${base}members/`),
  ]);
  return { workspaces: workspaceResult.workspaces, members: memberResult.members };
}

export function createWorkspace(tenantId: string, input: Pick<WorkspaceInput, "name" | "description">) {
  return mutate<{ workspace: OrganizationWorkspace }>(tenantPath(tenantId, "workspaces/"), "POST", input);
}

export function updateWorkspace(tenantId: string, workspaceId: string, input: Partial<WorkspaceInput>) {
  return mutate<{ workspace: OrganizationWorkspace }>(
    tenantPath(tenantId, `workspaces/${encodeURIComponent(workspaceId)}/`),
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
