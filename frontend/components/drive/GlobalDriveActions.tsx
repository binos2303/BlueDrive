"use client";

import { useEffect, useState } from "react";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";
import Toast from "@/components/ui/Toast";
import useDriveUploadIntake from "./browser/useDriveUploadIntake";
import { DRIVE_CREATE_FOLDER_EVENT, driveNewScope } from "./DriveNewMenu";
import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import { FOLDER_TREE_REFRESH_EVENT } from "@/lib/workspace-context";
import { captureDriveNewDestination } from "@/lib/drive-new-destination";
import useActiveWorkspaceId from "@/components/workspaces/useActiveWorkspaceId";

const noop = () => {};
const noLoad = async () => {};

/** Sidebar New works on every tab and pins actions to the selected Drive root. */
export default function GlobalDriveActions() {
  const workspaceId = useActiveWorkspaceId();
  const [message, setMessage] = useState<string | null>(null);
  const [folderOpen, setFolderOpen] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [folderWorkspaceId, setFolderWorkspaceId] = useState<string | null>(null);
  const { fileInputRef, folderInputRef, handleSelectedFiles } = useDriveUploadIntake({
    scope: "root", currentFolderId: null, listView: null, loadItems: noLoad,
    setToast: setMessage, setFileDropActive: noop, setDropTargetFolderId: noop, autoScrollDuringInternalDrag: noop,
  });
  useEffect(() => {
    function createFolder(event: Event) {
      if (driveNewScope(event) !== "root") return;
      setFolderWorkspaceId(captureDriveNewDestination("root", null).workspaceId);
      setName("Untitled folder"); setError(""); setFolderOpen(true);
    }
    window.addEventListener(DRIVE_CREATE_FOLDER_EVENT, createFolder);
    return () => window.removeEventListener(DRIVE_CREATE_FOLDER_EVENT, createFolder);
  }, []);

  async function createFolder() {
    if (!name.trim() || saving) return;
    setSaving(true); setError("");
    try {
      await requestAccountApi("/drive/api/folders/", {
        method: "POST", workspaceId: folderWorkspaceId, headers: await accountCsrfHeaders(),
        body: JSON.stringify({ name: name.trim(), parent_id: null }),
      });
      setFolderOpen(false); setMessage(`Created “${name.trim()}” in ${folderWorkspaceId ? "workspace files" : "My Drive"}.`);
      window.dispatchEvent(new CustomEvent(FOLDER_TREE_REFRESH_EVENT, { detail: { workspaceId: folderWorkspaceId } }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not create the folder."); }
    finally { setSaving(false); }
  }

  return <>
    <input ref={fileInputRef} type="file" multiple hidden aria-label={workspaceId ? "Upload files to workspace" : "Upload files to My Drive"} onChange={(event) => { handleSelectedFiles(event.currentTarget.files); event.currentTarget.value = ""; }} />
    <input ref={(input) => { folderInputRef.current = input; input?.setAttribute("webkitdirectory", ""); }} type="file" multiple hidden aria-label={workspaceId ? "Upload folder to workspace" : "Upload folder to My Drive"} onChange={(event) => { handleSelectedFiles(event.currentTarget.files); event.currentTarget.value = ""; }} />
    <Dialog open={folderOpen} title="New folder" description={folderWorkspaceId ? "This folder will be created in workspace files." : "This folder will be created in My Drive."} onClose={() => { if (!saving) setFolderOpen(false); }}>
      <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void createFolder(); }}>
        <label className="block text-sm font-medium">Folder name<input autoFocus required maxLength={255} value={name} disabled={saving} onFocus={(event) => event.currentTarget.select()} onChange={(event) => setName(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-border bg-background px-3 text-sm" /></label>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <div className="flex justify-end gap-2"><Button variant="secondary" disabled={saving} onClick={() => setFolderOpen(false)}>Cancel</Button><Button type="submit" loading={saving} disabled={!name.trim()}>Create</Button></div>
      </form>
    </Dialog>
    {message && <div className="fixed bottom-4 left-4 z-80 w-[min(24rem,calc(100vw-2rem))]"><Toast title="Drive" onDismiss={() => setMessage(null)}>{message}</Toast></div>}
  </>;
}
