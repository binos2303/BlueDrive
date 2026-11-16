import { getActiveWorkspaceIdForRequest } from "@/lib/workspace-context";

export type DriveNewScope = "root" | "current";

export function captureDriveNewDestination(scope: DriveNewScope, currentFolderId: number | null) {
  return {
    folderId: scope === "root" ? null : currentFolderId,
    workspaceId: getActiveWorkspaceIdForRequest(),
  };
}
