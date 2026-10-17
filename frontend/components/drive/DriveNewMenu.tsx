"use client";

import ContextMenu from "@/components/ui/ContextMenu";

export const DRIVE_UPLOAD_FILES_EVENT = "securedrive:upload-files";
export const DRIVE_UPLOAD_FOLDER_EVENT = "securedrive:upload-folder";
export const DRIVE_CREATE_FOLDER_EVENT = "securedrive:create-folder";

export default function DriveNewMenu() {
  return (
    <ContextMenu
      label="Create or upload"
      trigger={<><span aria-hidden="true">+</span><span>New</span></>}
      triggerClassName="flex h-9 w-full items-center justify-center gap-1.5 rounded-lg bg-brand px-2.5 font-sans text-[13px] font-semibold text-white transition-colors hover:bg-brand-hover"
      actions={[
        {
          label: "Upload files",
          onSelect: () => window.dispatchEvent(new Event(DRIVE_UPLOAD_FILES_EVENT)),
        },
        {
          label: "Upload folder",
          onSelect: () => window.dispatchEvent(new Event(DRIVE_UPLOAD_FOLDER_EVENT)),
        },
        {
          label: "New folder",
          onSelect: () => window.dispatchEvent(new Event(DRIVE_CREATE_FOLDER_EVENT)),
        },
      ]}
    />
  );
}
