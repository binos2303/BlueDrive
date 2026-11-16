"use client";

import { useState, type Dispatch, type SetStateAction } from "react";
import type { DriveListView, RenameResult, RenameTarget } from "@/lib/drive-service";
import type { DriveItem } from "./types";
import { applyStarredToItems, destructiveActionConfig, executeDuplicateItems, renameTargetForSelection } from "./drive-item-actions-utils";

type PendingDestructiveAction = {
  action: "trash" | "delete";
  count: number;
  targets: DriveItem[];
};

type Options = {
  title: string;
  listView: DriveListView | null;
  currentFolderId: number | null;
  clearSelection: () => void;
  clearSelectedIds: () => void;
  setDriveItems: Dispatch<SetStateAction<DriveItem[]>>;
  notifyFolderTreeChanged: () => void;
  loadItems: (folderId: number | null, view: DriveListView, queryOverride?: string) => Promise<void>;
  postItemAction: (path: string, targets: DriveItem[], extra?: Record<string, unknown>) => Promise<{ detail: string; count?: number }>;
  canManageItemsInDrive: (action: string) => boolean;
  setToast: (message: string | null) => void;
};

/**
 * Quản lý chung các thao tác thay đổi mục Drive: đổi tên, nhân bản, đánh dấu sao,
 * khôi phục và xóa. Giữ nguyên API, kiểm tra quyền và trình tự cập nhật giao diện.
 */
export default function useDriveItemActions({
  title, listView, currentFolderId, clearSelection, clearSelectedIds, setDriveItems,
  notifyFolderTreeChanged, loadItems, postItemAction, canManageItemsInDrive, setToast,
}: Options) {
  const [renameTarget, setRenameTarget] = useState<RenameTarget | null>(null);
  const [isDuplicatingItems, setIsDuplicatingItems] = useState(false);
  const [pendingDestructive, setPendingDestructive] = useState<PendingDestructiveAction | null>(null);

  function openRenameDialog(targets: DriveItem[]) {
    const target = renameTargetForSelection(targets, title);
    if (target) setRenameTarget(target);
  }

  function handleRenamed(result: RenameResult) {
    setRenameTarget(null);
    clearSelectedIds();
    if (result.changed) {
      setToast(result.detail);
      notifyFolderTreeChanged();
      if (listView) void loadItems(listView === "drive" ? currentFolderId : null, listView);
    }
  }

  async function duplicateItems(targets: DriveItem[]) {
    if (!targets.length || isDuplicatingItems) return;
    if (!canManageItemsInDrive("Duplicate")) return;
    setIsDuplicatingItems(true);
    try {
      await executeDuplicateItems(targets, {
        postItemAction: (items) => postItemAction("/drive/api/items/duplicate/", items),
        clearSelectedIds, notifyFolderTreeChanged,
        refreshItems: () => listView ? loadItems(listView === "drive" ? currentFolderId : null, listView) : Promise.resolve(),
        setToast,
      });
    } finally {
      setIsDuplicatingItems(false);
    }
  }

  async function restoreItems(targets: DriveItem[]) {
    if (!targets.length) return;
    try {
      const result = await postItemAction("/drive/api/items/restore/", targets);
      clearSelectedIds();
      notifyFolderTreeChanged();
      if (listView) await loadItems(listView === "drive" ? currentFolderId : null, listView);
      setToast(result.detail || "Items restored successfully.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not restore selected items.");
    }
  }

  async function applyDestructiveAction(pending: PendingDestructiveAction) {
    const { path, defaultMessage } = destructiveActionConfig(pending.action);
    try {
      const result = await postItemAction(path, pending.targets);
      clearSelection();
      notifyFolderTreeChanged();
      if (listView) await loadItems(listView === "drive" ? currentFolderId : null, listView);
      setToast(result.detail || defaultMessage);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "The file operation failed. No success was reported.");
    }
  }

  async function toggleStar(targets: DriveItem[], desired?: boolean) {
    if (!targets.length) return;
    const shouldStar = desired ?? !targets.every((item) => item.starred);
    try {
      const result = await postItemAction("/drive/api/items/star/", targets, { starred: shouldStar });
      setDriveItems((current) => applyStarredToItems(current, targets, shouldStar));
      clearSelectedIds();
      if (listView && listView !== "drive") {
        await loadItems(null, listView);
      }
      setToast(result.detail || (shouldStar ? "Added to Starred." : "Removed from Starred."));
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not update Starred.");
    }
  }


  return {
    renameTarget, setRenameTarget, openRenameDialog, handleRenamed,
    isDuplicatingItems, duplicateItems,
    restoreItems, toggleStar,
    pendingDestructive, setPendingDestructive, applyDestructiveAction,
  };
}
