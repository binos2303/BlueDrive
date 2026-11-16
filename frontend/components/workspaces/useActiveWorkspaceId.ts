"use client";

import { useSyncExternalStore } from "react";
import { usePathname } from "next/navigation";
import { workspaceIdFromPathname } from "@/lib/drive-paths";
import { getActiveWorkspaceIdForRequest, WORKSPACE_CHANGED_EVENT } from "@/lib/workspace-context";

function subscribe(onChange: () => void) {
  window.addEventListener(WORKSPACE_CHANGED_EVENT, onChange);
  return () => window.removeEventListener(WORKSPACE_CHANGED_EVENT, onChange);
}

/** Navigation and file requests must describe the same selected workspace. */
export default function useActiveWorkspaceId() {
  const pathname = usePathname();
  const savedWorkspaceId = useSyncExternalStore(subscribe, getActiveWorkspaceIdForRequest, () => null);
  return pathname === "/drive" || pathname.startsWith("/drive/")
    ? workspaceIdFromPathname(pathname) : savedWorkspaceId;
}
