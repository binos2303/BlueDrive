"use client";

import { createContext, useContext } from "react";
import type { OrganizationWorkspace } from "@/lib/workspace-service";

// Reuse the workspace already loaded by the switcher; APIs still authorize every write.
export const SelectedWorkspaceContext = createContext<OrganizationWorkspace | null>(null);

export function useSelectedWorkspace() {
  return useContext(SelectedWorkspaceContext);
}

export function canEditSelectedWorkspace(workspace: OrganizationWorkspace | null, workspaceId: string) {
  return workspace?.id === workspaceId && (workspace.canManage || workspace.currentUserRole === "editor" || workspace.currentUserRole === "admin");
}
