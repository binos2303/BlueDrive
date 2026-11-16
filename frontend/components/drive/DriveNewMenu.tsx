"use client";

import ContextMenu from "@/components/ui/ContextMenu";
import { Plus } from "lucide-react";
import useActiveWorkspaceId from "@/components/workspaces/useActiveWorkspaceId";
import { canEditSelectedWorkspace, useSelectedWorkspace } from "@/components/workspaces/SelectedWorkspaceContext";
import type { DriveNewScope } from "@/lib/drive-new-destination";

export const DRIVE_UPLOAD_FILES_EVENT = "securedrive:upload-files";
export const DRIVE_UPLOAD_FOLDER_EVENT = "securedrive:upload-folder";
export const DRIVE_CREATE_FOLDER_EVENT = "securedrive:create-folder";

export type { DriveNewScope } from "@/lib/drive-new-destination";

export function driveNewScope(event: Event): DriveNewScope {
  return (event as CustomEvent<{ scope?: DriveNewScope }>).detail?.scope ?? "current";
}

export default function DriveNewMenu({ scope = "root", label = "New", onAction }: { scope?: DriveNewScope; label?: string; onAction?: () => void }) {
  const workspaceId = useActiveWorkspaceId();
  const workspace = useSelectedWorkspace();
  if (workspaceId && !canEditSelectedWorkspace(workspace, workspaceId)) return null;
  const dispatch = (name: string) => {
    window.dispatchEvent(new CustomEvent(name, { detail: { scope } }));
    onAction?.();
  };
  return (
    <ContextMenu
      label={workspaceId ? "New in workspace files" : "New in My Drive"}
      trigger={<><Plus size={18} aria-hidden="true" /><span>{label}</span></>}
      header={<p className="text-xs text-muted">{workspaceId ? "New items go to workspace files" : "New items go to My Drive"}</p>}
      triggerClassName="ui-control flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand-contrast px-4 text-sm font-semibold text-on-accent transition-colors hover:bg-brand-hover"
      actions={[
        {
          label: "Upload files",
          onSelect: () => dispatch(DRIVE_UPLOAD_FILES_EVENT),
        },
        {
          label: "Upload folder",
          onSelect: () => dispatch(DRIVE_UPLOAD_FOLDER_EVENT),
        },
        {
          label: "New folder",
          onSelect: () => dispatch(DRIVE_CREATE_FOLDER_EVENT),
        },
      ]}
    />
  );
}
