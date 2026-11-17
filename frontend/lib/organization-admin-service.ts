import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import type { OrganizationWorkspace, WorkspaceStatus, WorkspaceRemovalRequest } from "@/lib/workspace-service";

export type OrganizationMember = {
  membershipId: string;
  userId: number;
  username: string;
  email: string;
  role: "owner" | "admin" | "member" | string;
  status: "active" | "invited" | "suspended" | "revoked" | string;
  managed?: boolean;
  myDriveWorkspaceId?: string | null;
};

export type OrganizationDirectoryRow = {
  id: string; name: string; status: string; workspaces: number; created_at: string;
  pendingAdministratorInvitation?: boolean;
};

export type OrganizationDirectory = {
  count: number; page: number; page_size: number; results: OrganizationDirectoryRow[];
  capabilities?: { createOrganization: boolean; reinviteOrganization: boolean };
};

export type OrganizationAccountCapabilities = { inviteAccounts: boolean; manageAccounts: boolean };
export type OrganizationAccountResult = {
  member: OrganizationMember;
  myDrive: { tenantId: string; workspaceId: string; ownership: "organization" };
  storageReady: boolean;
};

export type ProvisionOrganizationInput = {
  name: string; slug: string; admin: { username: string; email: string };
  limit_bytes: number; member_limit_bytes: number; reason: string;
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

async function mutate<T>(path: string, method: "POST" | "PATCH" | "DELETE", body?: unknown, idempotencyKey?: string): Promise<T> {
  return requestAccountApi<T>(path, {
    method,
    headers: { ...await accountCsrfHeaders(), ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

/** Get only organization workspaces and members; access is assigned per user. */
export async function getOrganizationAdminData(tenantId: string): Promise<{
  workspaces: OrganizationWorkspace[];
  members: OrganizationMember[];
  capabilities: OrganizationAccountCapabilities;
}> {
  const base = tenantPath(tenantId);
  const [workspaceResult, memberResult] = await Promise.all([
    requestAccountApi<{ workspaces: OrganizationWorkspace[] }>(`${base}workspaces/`),
    requestAccountApi<{ members: OrganizationMember[]; capabilities?: OrganizationAccountCapabilities }>(`${base}members/`),
  ]);
  return { workspaces: workspaceResult.workspaces, members: memberResult.members,
    capabilities: memberResult.capabilities ?? { inviteAccounts: false, manageAccounts: false } };
}

export function provisionOrganization(input: ProvisionOrganizationInput, idempotencyKey: string) {
  return mutate<OrganizationAccountResult & { organization: OrganizationDirectoryRow }>(
    "/accounts/api/admin/organizations/", "POST", input, idempotencyKey);
}

export function inviteOrganizationMember(
  tenantId: string, input: { username: string; email: string; limit_bytes: number; reason: string }, idempotencyKey: string,
) {
  return mutate<OrganizationAccountResult>(tenantPath(tenantId, "members/"), "POST", input, idempotencyKey);
}

export function manageOrganizationMember(tenantId: string, membershipId: string, action: "suspend" | "restore" | "reinvite", reason = "") {
  return mutate<unknown>(tenantPath(tenantId, `memberships/${encodeURIComponent(membershipId)}/${action}/`), "POST", action === "reinvite" ? { reason } : {});
}

export function reinviteOrganizationAdministrator(tenantId: string, reason: string) {
  return mutate<unknown>(`/accounts/api/admin/organizations/${encodeURIComponent(tenantId)}/reinvite/`, "POST", { reason });
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

export type WorkspaceRemovalRequests = { requests: WorkspaceRemovalRequest[]; count: number; page: number; pageSize: number; hasNext: boolean };

export function getWorkspaceRemovalRequests(tenantId: string, page = 1) {
  return requestAccountApi<WorkspaceRemovalRequests>(tenantPath(tenantId, `workspace-removal-requests/?page=${page}`));
}

export function decideWorkspaceRemoval(tenantId: string, requestId: string, decision: "approve" | "reject", reason: string) {
  return mutate<{ request: WorkspaceRemovalRequest }>(tenantPath(tenantId, `workspace-removal-requests/${encodeURIComponent(requestId)}/decision/`), "POST", { decision, reason });
}
