/** UI policy only; backend checks authorization independently. */
export type ManagedMember = {
  isSelf: boolean;
  isProtected: boolean;
  workspaceRole: "admin" | "editor" | "viewer";
};

export function canModifyWorkspaceMember(member: ManagedMember): boolean {
  return !member.isSelf && !member.isProtected;
}

export function isWorkspaceRole(value: string): value is ManagedMember["workspaceRole"] {
  return value === "admin" || value === "editor" || value === "viewer";
}
