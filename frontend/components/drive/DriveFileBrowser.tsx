"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Grid2x2,
  List,
  Search,
  X,
} from "lucide-react";
import Breadcrumb from "@/components/ui/Breadcrumb";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import type { ContextMenuAction } from "@/components/ui/ContextMenu";
import EmptyState from "@/components/shared/EmptyState";
import Toast from "@/components/ui/Toast";
import RenameDialog from "@/components/drive/RenameDialog";
import ShareManagementDialog from "@/components/drive/ShareManagementDialog";
import { type ShareTarget } from "@/lib/share-service";
import { canOpenShareManagement } from "@/lib/share-policy";
import FilePreviewDialog, { type PreviewFile } from "@/components/drive/FilePreviewDialog";
import DriveNewMenu, { DRIVE_CREATE_FOLDER_EVENT } from "@/components/drive/DriveNewMenu";
import {
  downloadDriveFile,
  downloadDriveFolder,
  type DownloadProgress,
} from "@/lib/drive-service";
import {
  accountCsrfHeaders,
  requestAccountApi,
} from "@/lib/account-service";
import { isDownloadSelectionSupported } from "@/lib/drive-download-policy";
import type { DriveItem } from "./browser/types";
import { listViewForTitle } from "./browser/drive-display-utils";
import useDriveItems from "./browser/useDriveItems";
import DriveGrid from "./browser/DriveGrid";
import DriveListTable from "./browser/DriveListTable";
import DriveActionToolbar from "./browser/DriveActionToolbar";
import DriveCreateFolderDialog from "./browser/DriveCreateFolderDialog";
import DriveMoveDialog from "./browser/DriveMoveDialog";
import DriveShareDialog from "./browser/DriveShareDialog";
import useDriveSelection from "./browser/useDriveSelection";
import useDriveItemActions from "./browser/useDriveItemActions";
import useDriveFileOperations from "./browser/useDriveFileOperations";
import useDriveUploadIntake from "./browser/useDriveUploadIntake";
import { DRIVE_SEARCH_CHANGED_EVENT, FOLDER_TREE_REFRESH_EVENT, WORKSPACE_CHANGED_EVENT } from "@/lib/workspace-context";

type ViewMode = "list" | "grid";
export type { DriveItem } from "./browser/types";
type ScrollMetrics = {
  scrollTop: number;
  clientHeight: number;
  scrollHeight: number;
  /** Content-space offset for the first row/card, excluding the table/group heading. */
  trackTop: number;
};

type ScrollbarDrag = {
  pointerId: number;
  startY: number;
  startThumbTop: number;
} | null;

type DriveFileBrowserProps = {
  title: string;
  items: DriveItem[];
};

export default function DriveFileBrowser({ title, items }: DriveFileBrowserProps) {
  const pathname = usePathname();
  // Remount on route/folder changes instead of synchronously resetting state in an effect.
  return <DriveFileBrowserContent key={`${title}:${pathname}`} title={title} items={items} />;
}

function DriveFileBrowserContent({ title, items }: DriveFileBrowserProps) {
  const listView = listViewForTitle(title);
  const pathname = usePathname();
  const router = useRouter();
  const currentFolderId = useMemo(() => {
    if (title !== "My Drive") return null;
    const match = pathname.match(/^\/drive\/folders\/([1-9]\d*)\/?$/);
    if (!match) return null;
    const parsed = Number(match[1]);
    return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
  }, [pathname, title]);
  const {
    driveItems, setDriveItems,
    searchQuery, setSearchQuery, searchQueryRef,
    loading, loadError, folderDetails, setFolderDetails,
    sortKey, setSortKey, sortDirection, setSortDirection,
    sortedItems, folderItems, fileItems,
    loadItems,
  } = useDriveItems(items, listView);
  const [view, setView] = useState<ViewMode>("list");
  const [isCreateFolderOpen, setIsCreateFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("Untitled folder");
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const [folderNameError, setFolderNameError] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const [downloadStatus, setDownloadStatus] = useState<{
    text: string;
    progress: DownloadProgress | null;
  } | null>(null);
  const [shareDialogOpen, setShareDialogOpen] = useState(false);
  const [manageShareTarget, setManageShareTarget] = useState<ShareTarget | null>(null);
  const [shareTargets, setShareTargets] = useState<DriveItem[]>([]);
  const [shareEmail, setShareEmail] = useState("");
  const [sharePermission, setSharePermission] = useState<"viewer" | "editor">("viewer");
  const [sharing, setSharing] = useState(false);
  const [previewTarget, setPreviewTarget] = useState<PreviewFile | null>(null);
  // Only OS/browser file drags activate the upload overlay. Internal Drive drags
  // must never wash out the whole interface.
  const [fileDropActive, setFileDropActive] = useState(false);
  const driveListRef = useRef<HTMLDivElement>(null);
  const scrollbarTrackRef = useRef<HTMLDivElement>(null);
  const scrollbarDragRef = useRef<ScrollbarDrag>(null);
  const [scrollMetrics, setScrollMetrics] = useState<ScrollMetrics>({
    scrollTop: 0,
    clientHeight: 0,
    scrollHeight: 0,
    trackTop: 0,
  });

  const {
    selectedIds,
    selectedItems,
    marqueeActive,
    selectionBox,
    clearSelection,
    clearSelectedIds,
    handleItemClick,
    toggleItem,
    handleMarqueePointerDown,
  } = useDriveSelection({ items: driveItems, sortedItems, containerRef: driveListRef });

  // Gom các thao tác thay đổi file/thư mục vào một hook theo cùng trách nhiệm nghiệp vụ.
  const {
    renameTarget, setRenameTarget, openRenameDialog, handleRenamed,
    isDuplicatingItems, duplicateItems, restoreItems, toggleStar,
    pendingDestructive, setPendingDestructive, applyDestructiveAction,
  } = useDriveItemActions({
    title, listView, currentFolderId,
    clearSelection, clearSelectedIds, setDriveItems,
    notifyFolderTreeChanged, loadItems, postItemAction,
    canManageItemsInDrive, setToast,
  });

  // Tập trung nghiệp vụ di chuyển và kéo thả nội bộ; upload từ máy tính vẫn ở component chính.
  const {
    isMoveDialogOpen, setIsMoveDialogOpen, moveTargets,
    moveDestinationId, moveDestinationItems, moveDestinationDetails,
    moveDestinationLoading, moveDestinationError, isMovingItems,
    dropTargetFolderId, setDropTargetFolderId, breadcrumbDropTargetIndex,
    loadMoveDestination, openMoveDialog, confirmMoveItems,
    handleBreadcrumbDragOver, handleBreadcrumbDragLeave, handleBreadcrumbDrop,
    autoScrollDuringInternalDrag, handleDragStart, handleFolderDragOver, handleDropOnFolder,
  } = useDriveFileOperations({
    title, listView, currentFolderId, folderDetails, driveItems,
    selectedIds, selectedItems, setFileDropActive,
    clearSelectedIds, notifyFolderTreeChanged, loadItems,
    postItemAction, canManageItemsInDrive, setToast,
  });

  // Nhận dữ liệu từ máy người dùng; thao tác Move nội bộ vẫn do useDriveFileOperations phụ trách.
  const {
    fileInputRef, folderInputRef, dragMessage,
    handleSelectedFiles, handleDragEnter, handleDragLeave, handleDragOver, handleDrop,
  } = useDriveUploadIntake({
    currentFolderId, listView, loadItems, setToast, setFileDropActive,
    setDropTargetFolderId, autoScrollDuringInternalDrag,
  });

  const updateScrollMetrics = useCallback(() => {
    const container = driveListRef.current;
    if (!container) return;
    const containerRect = container.getBoundingClientRect();
    const tableHeader = container.querySelector("thead");
    const firstDriveItem = container.querySelector<HTMLElement>("[data-drive-item-id]");
    // In list view, start the custom scrollbar below the sticky column headings.
    // In grid view, align it with the first folder/file card rather than the section title.
    const trackTop = tableHeader instanceof HTMLElement
      ? tableHeader.getBoundingClientRect().height
      : firstDriveItem
        ? Math.max(0, firstDriveItem.getBoundingClientRect().top - containerRect.top + container.scrollTop)
        : 0;
    const next: ScrollMetrics = {
      scrollTop: container.scrollTop,
      clientHeight: container.clientHeight,
      scrollHeight: container.scrollHeight,
      trackTop: Math.round(trackTop),
    };
    setScrollMetrics((current) => (
      current.scrollTop === next.scrollTop
      && current.clientHeight === next.clientHeight
      && current.scrollHeight === next.scrollHeight
      && current.trackTop === next.trackTop
        ? current
        : next
    ));
  }, []);

  useEffect(() => {
    const container = driveListRef.current;
    if (!container) return;
    const initialMeasureFrame = window.requestAnimationFrame(updateScrollMetrics);
    container.addEventListener("scroll", updateScrollMetrics, { passive: true });
    const observer = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(updateScrollMetrics)
      : null;
    observer?.observe(container);
    if (container.firstElementChild instanceof HTMLElement) {
      observer?.observe(container.firstElementChild);
    }
    return () => {
      window.cancelAnimationFrame(initialMeasureFrame);
      container.removeEventListener("scroll", updateScrollMetrics);
      observer?.disconnect();
    };
  }, [updateScrollMetrics, loading, view, driveItems.length, sortKey, sortDirection]);

  // The custom scrollbar occupies only the file/folder rows, not the column heading
  // or the Folders/Files group label. Keep the same 8px inset at the bottom.
  const scrollbarTrackHeight = Math.max(0, scrollMetrics.clientHeight - scrollMetrics.trackTop - 8);
  const scrollbarThumbHeight = useMemo(() => {
    if (scrollMetrics.clientHeight <= 0 || scrollbarTrackHeight <= 0) return 0;
    const visibleItemsHeight = Math.max(0, scrollMetrics.clientHeight - scrollMetrics.trackTop);
    if (scrollMetrics.scrollHeight <= scrollMetrics.clientHeight + 1) return scrollbarTrackHeight;
    const naturalHeight = scrollbarTrackHeight * visibleItemsHeight / scrollMetrics.scrollHeight;
    // A deliberately shorter thumb improves visual balance; dragging still maps to the full scroll range.
    return Math.min(scrollbarTrackHeight, Math.max(28, Math.round(naturalHeight * 0.66)));
  }, [scrollMetrics.clientHeight, scrollMetrics.scrollHeight, scrollMetrics.trackTop, scrollbarTrackHeight]);
  const maxScrollTop = Math.max(0, scrollMetrics.scrollHeight - scrollMetrics.clientHeight);
  const maxThumbTop = Math.max(0, scrollbarTrackHeight - scrollbarThumbHeight);
  const scrollbarThumbTop = maxScrollTop > 0
    ? (scrollMetrics.scrollTop / maxScrollTop) * maxThumbTop
    : 0;

  function handleScrollbarPointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    const container = driveListRef.current;
    if (!container || maxScrollTop <= 0 || scrollbarThumbHeight <= 0) return;
    event.preventDefault();
    event.stopPropagation();

    const rect = event.currentTarget.getBoundingClientRect();
    const travel = Math.max(0, event.currentTarget.clientHeight - scrollbarThumbHeight);
    const clickedThumb = event.target instanceof Element
      && Boolean(event.target.closest("[data-drive-scroll-thumb]"));
    let startThumbTop = scrollbarThumbTop;
    if (!clickedThumb && travel > 0) {
      startThumbTop = Math.max(0, Math.min(
        travel,
        event.clientY - rect.top - scrollbarThumbHeight / 2,
      ));
      container.scrollTop = (startThumbTop / travel) * maxScrollTop;
    }

    scrollbarDragRef.current = {
      pointerId: event.pointerId,
      startY: event.clientY,
      startThumbTop,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleScrollbarPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const drag = scrollbarDragRef.current;
    const container = driveListRef.current;
    if (!drag || !container || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    const travel = Math.max(0, event.currentTarget.clientHeight - scrollbarThumbHeight);
    const nextThumbTop = Math.max(0, Math.min(
      travel,
      drag.startThumbTop + event.clientY - drag.startY,
    ));
    if (travel > 0 && maxScrollTop > 0) {
      container.scrollTop = (nextThumbTop / travel) * maxScrollTop;
    }
  }

  function finishScrollbarPointer(event: React.PointerEvent<HTMLDivElement>) {
    const drag = scrollbarDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    scrollbarDragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handleScrollbarKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const container = driveListRef.current;
    if (!container) return;
    const pageStep = Math.max(40, Math.round(container.clientHeight * 0.85));
    let nextTop: number | null = null;
    if (event.key === "ArrowUp") nextTop = container.scrollTop - 40;
    else if (event.key === "ArrowDown") nextTop = container.scrollTop + 40;
    else if (event.key === "PageUp") nextTop = container.scrollTop - pageStep;
    else if (event.key === "PageDown" || event.key === " ") nextTop = container.scrollTop + pageStep;
    else if (event.key === "Home") nextTop = 0;
    else if (event.key === "End") nextTop = container.scrollHeight;
    if (nextTop === null) return;
    event.preventDefault();
    container.scrollTop = nextTop;
  }

  useEffect(() => {
    if (!listView) return;
    const initialQuery = listView === "drive"
      ? new URLSearchParams(window.location.search).get("q")?.trim().slice(0, 255) ?? ""
      : "";
    searchQueryRef.current = initialQuery;
    const timer = window.setTimeout(() => {
      setSearchQuery(initialQuery);
      void loadItems(listView === "drive" && !initialQuery ? currentFolderId : null, listView, initialQuery);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [listView, currentFolderId, loadItems, searchQueryRef, setSearchQuery]);

  useEffect(() => {
    const handleSearchChanged = (event: Event) => {
      const customEvent = event as CustomEvent<{ query?: string }>;
      const query = (customEvent.detail?.query ?? "").trim().slice(0, 255);
      searchQueryRef.current = query;
      setSearchQuery(query);
      clearSelection();
      setFolderDetails(null);
      if (query) {
        void loadItems(null, "drive", query);
      } else if (listView === "drive") {
        void loadItems(currentFolderId, "drive", "");
      }
    };
    const handleHistoryNavigation = () => {
      const query = (new URLSearchParams(window.location.search).get("q") ?? "").trim().slice(0, 255);
      if (query === searchQueryRef.current) return;
      searchQueryRef.current = query;
      setSearchQuery(query);
      clearSelection();
      if (listView === "drive") void loadItems(query ? null : currentFolderId, "drive", query);
    };
    window.addEventListener(DRIVE_SEARCH_CHANGED_EVENT, handleSearchChanged);
    window.addEventListener("popstate", handleHistoryNavigation);
    return () => {
      window.removeEventListener(DRIVE_SEARCH_CHANGED_EVENT, handleSearchChanged);
      window.removeEventListener("popstate", handleHistoryNavigation);
    };
  }, [currentFolderId, listView, loadItems, clearSelection, searchQueryRef, setSearchQuery, setFolderDetails]);

  useEffect(() => {
    function handleWorkspaceChanged() {
      setPreviewTarget(null);
      setRenameTarget(null);
      setManageShareTarget(null);
      setShareDialogOpen(false);
      searchQueryRef.current = "";
      setSearchQuery("");
      clearSelection();
      setFolderDetails(null);
      if (currentFolderId !== null) {
        // A folder ID is not portable between workspaces. Return to the selected
        // workspace root rather than leaving a stale folder route on screen.
        router.replace("/drive");
        return;
      }
      if (listView) void loadItems(null, listView, "");
    }

    window.addEventListener(WORKSPACE_CHANGED_EVENT, handleWorkspaceChanged);
    return () => window.removeEventListener(WORKSPACE_CHANGED_EVENT, handleWorkspaceChanged);
  }, [currentFolderId, listView, loadItems, router, clearSelection, searchQueryRef, setSearchQuery, setFolderDetails, setRenameTarget]);

  const selectedCanManage = selectedItems.length > 0 && selectedItems.every((item) => item.canManage !== false);
  const selectedCanShare = selectedItems.length > 0 && canOpenShareManagement(selectedItems);

  async function handleCreateFolder() {
    const trimmedName = newFolderName.trim();

    if (!trimmedName) {
      setFolderNameError("Folder name cannot be empty.");
      return;
    }

    if (trimmedName.length > 255) {
      setFolderNameError("Folder name cannot exceed 255 characters.");
      return;
    }

    setIsCreatingFolder(true);
    setFolderNameError("");
    setToast("Creating folder...");

    try {
      await requestAccountApi<{
        id: number;
        name: string;
        parent_id: number | null;
        type: "folder";
      }>("/drive/api/folders/", {
        method: "POST",
        headers: await accountCsrfHeaders(),
        body: JSON.stringify({
          name: trimmedName,
          parent_id: currentFolderId,
        }),
      });

      setIsCreateFolderOpen(false);
      setNewFolderName("Untitled folder");
      notifyFolderTreeChanged();

      // Refresh the list first; hide the progress toast after the folder is shown.
      await loadItems(
        currentFolderId,
        listView ?? "drive",
      );
      setToast(null);
    } catch (error) {
      setToast(null);
      setFolderNameError(
        error instanceof Error ? error.message : "Could not create the folder.",
      );
    } finally {
      setIsCreatingFolder(false);
    }
  }

  // Tạo thư mục thủ công là thao tác nghiệp vụ riêng, không thuộc hàng đợi Upload.
  useEffect(() => {
    function onCreateFolder() {
      if (title !== "My Drive") {
        setToast("Creating folders is only available in My Drive.");
        return;
      }
      setNewFolderName("Untitled folder");
      setFolderNameError("");
      setIsCreateFolderOpen(true);
    }
    window.addEventListener(DRIVE_CREATE_FOLDER_EVENT, onCreateFolder);
    return () => window.removeEventListener(DRIVE_CREATE_FOLDER_EVENT, onCreateFolder);
  }, [title]);

  function showNotConnected(action: string) {
    setToast(`${action} isn't connected yet. No files were changed.`);
  }

  function notifyFolderTreeChanged() {
    window.dispatchEvent(new Event(FOLDER_TREE_REFRESH_EVENT));
  }

  function openItem(item: DriveItem) {
    if (item.type !== "folder") {
      setPreviewTarget({ id: item.id, name: item.name });
      return;
    }
    if (!Number.isSafeInteger(item.folderId) || !item.folderId || item.folderId <= 0) {
      setToast("This folder has an invalid ID and cannot be opened.");
      return;
    }
    clearSelectedIds();
    router.push(`/drive/folders/${item.folderId}`);
  }

  function actionTargets(item?: DriveItem): DriveItem[] {
    return item ? [item] : selectedItems;
  }

  function driveItemPayload(targets: DriveItem[]) {
    return {
      file_ids: targets.filter((target) => target.type !== "folder").map((target) => target.id),
      folder_ids: targets
        .filter((target) => target.type === "folder")
        .map((target) => target.folderId ?? Math.abs(target.id)),
    };
  }

  function canManageItemsInDrive(action: string): boolean {
    if (title === "Shared with me" || title === "Trash") {
      setToast(`${action} is available for items in My Drive and Recent only.`);
      return false;
    }
    return true;
  }

  async function postItemAction(path: string, targets: DriveItem[], extra: Record<string, unknown> = {}) {
    const payload = { ...driveItemPayload(targets), ...extra };
    return requestAccountApi<{ detail: string; count?: number }>(path, {
      method: "POST",
      headers: await accountCsrfHeaders(),
      body: JSON.stringify(payload),
    });
  }

  function openShareDialog(targets: DriveItem[]) {
    if (!targets.length) {
      setToast("Select at least one item to share.");
      return;
    }
    if (!canManageItemsInDrive("Share")) return;
    if (!canOpenShareManagement(targets)) {
      setToast("Only the original owner with edit permission can manage direct shares.");
      return;
    }
    if (targets.length === 1) {
      const item = targets[0];
      setManageShareTarget({ kind: item.type === "folder" ? "folder" : "file", id: item.type === "folder" ? item.folderId ?? Math.abs(item.id) : item.id, name: item.name });
      return;
    }
    setShareTargets(targets);
    setShareEmail("");
    setSharePermission("viewer");
    setShareDialogOpen(true);
  }

  async function submitShare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!shareTargets.length || sharing) return;
    setSharing(true);
    try {
      const result = await postItemAction("/drive/api/items/share/", shareTargets, {
        email: shareEmail.trim(),
        permission: sharePermission,
      });
      setShareDialogOpen(false);
      setShareTargets([]);
      setShareEmail("");
      setToast(result.detail || "Sharing permission updated.");
      if (listView) await loadItems(listView === "drive" ? currentFolderId : null, listView);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not share selected items.");
    } finally {
      setSharing(false);
    }
  }

  function runAction(action: string, item?: DriveItem) {
    const targets = actionTargets(item);
    if (action === "Open" && item) {
      openItem(item);
    } else if (action === "Rename") {
      openRenameDialog(targets);
    } else if (action === "Download") {
      void downloadItems(targets);
    } else if (action === "Move") {
      openMoveDialog(targets);
    } else if (action === "Duplicate") {
      void duplicateItems(targets);
    } else if (action === "Restore") {
      void restoreItems(targets);
    } else if (action === "Add to Starred") {
      void toggleStar(targets, true);
    } else if (action === "Remove from Starred") {
      void toggleStar(targets, false);
    } else if (action === "Share") {
      openShareDialog(targets);
    } else if (action === "Move to trash" || action === "Move folder to trash" || action === "Delete permanently") {
      setPendingDestructive({
        action: action === "Delete permanently" ? "delete" : "trash",
        count: targets.length,
        targets,
      });
    } else {
      showNotConnected(action);
    }
  }

  async function downloadItems(targets: Pick<DriveItem, "id" | "folderId" | "name" | "type">[]) {
    if (!targets.length) {
      setDownloadStatus({ text: "Failed: select an item to download.", progress: null });
      return;
    }
    if (!isDownloadSelectionSupported(targets)) {
      setToast("Select one folder at a time to download its ZIP. Mixed and multiple-folder downloads aren't supported yet.");
      return;
    }
    for (const target of targets) {
      setDownloadStatus({ text: `Preparing ${target.name}`, progress: null });
      try {
        let latestProgress: DownloadProgress | null = null;
        const onProgress = ({ loaded, total }: DownloadProgress) => {
          latestProgress = { loaded, total };
          const amount = total ? ` ${Math.round((loaded / total) * 100)}%` : "";
          setDownloadStatus({ text: `Downloading ${target.name}${amount}`, progress: latestProgress });
        };
        if (target.type === "folder") {
          const folderId = target.folderId ?? Math.abs(target.id);
          await downloadDriveFolder(folderId, target.name, onProgress);
        } else {
          await downloadDriveFile(target.id, target.name, onProgress);
        }
        setDownloadStatus({
          text: `Completed: ${target.name} received; browser save started.`,
          progress: latestProgress,
        });
      } catch (error) {
        setDownloadStatus({
          text: `Failed: ${error instanceof Error ? error.message : "Download failed."}`,
          progress: null,
        });
        return;
      }
    }
  }

  function createActions(item?: DriveItem): ContextMenuAction[] {
    const actionTarget = item ? [item] : selectedItems;
    const onlySelectedFolder = actionTarget.length === 1 && actionTarget[0].type === "folder";
    const canManageTargets = actionTarget.length > 0 && actionTarget.every((target) => target.canManage !== false);
    const actions: ContextMenuAction[] = [];

    if (actionTarget.length === 1) {
      actions.push({
        label: "Open",
        onSelect: () => runAction("Open", actionTarget[0]),
      });
    }
    actions.push({ label: "Download", onSelect: () => runAction("Download", item) });
    if (canManageTargets && title !== "Trash") {
      actions.push({ label: "Rename", onSelect: () => runAction("Rename", item), disabled: actionTarget.length !== 1 });
    }
    if (canManageTargets && title !== "Shared with me" && title !== "Trash") {
      actions.push(
        { label: "Move", onSelect: () => runAction("Move", item) },
        { label: "Duplicate", onSelect: () => runAction("Duplicate", item) },
      );
    }
    if (title !== "Trash") {
      const allStarred = actionTarget.length > 0 && actionTarget.every((target) => target.starred);
      actions.push({
        label: allStarred ? "Remove from Starred" : "Add to Starred",
        onSelect: () => runAction(allStarred ? "Remove from Starred" : "Add to Starred", item),
      });
    }
    if (canManageTargets && canOpenShareManagement(actionTarget) && title !== "Shared with me" && title !== "Trash") {
      actions.push({ label: actionTarget.length === 1 ? "Manage access" : "Share", onSelect: () => runAction("Share", item) });
    }
    if (title === "Trash") {
      actions.push(
        { label: "Restore", onSelect: () => runAction("Restore", item) },
        {
          label: "Delete permanently",
          onSelect: () => runAction("Delete permanently", item),
          destructive: true,
        },
      );
    } else if (canManageTargets && title !== "Shared with me") {
      actions.push({
        label: onlySelectedFolder ? "Move folder to trash" : "Move to trash",
        onSelect: () => runAction("Move to trash", item),
        destructive: true,
      });
    }
    return actions;
  }

  const folderPath = [
    {
      label: title,
      onSelect: currentFolderId !== null ? () => router.push("/drive") : undefined,
    },
    ...(folderDetails?.ancestors ?? []).map((ancestor) => ({
      label: ancestor.name,
      onSelect: () => router.push(`/drive/folders/${ancestor.id}`),
    })),
    ...(currentFolderId !== null
      ? [{ label: folderDetails?.name ?? "Loading folder…" }]
      : []),
  ];
  const toastTitle = toast?.toLowerCase().includes("creating folder")
    ? "Creating folder"
    : toast?.toLowerCase().includes("canceled")
      ? "Selection canceled"
      : toast?.toLowerCase().includes("browser")
        || toast?.toLowerCase().includes("cannot be added")
        || toast?.toLowerCase().includes("couldn't")
        || toast?.toLowerCase().includes("could not")
        ? "Upload issue"
        : "Notification";
  const toastVariant = toastTitle === "Selection canceled" || toastTitle === "Creating folder"
    ? "info"
    : toastTitle === "Upload issue"
      ? "error"
      : "warning";

  // Event/effect callbacks below capture refs safely; the React Hooks refs rule
  // can falsely attribute those callback reads to the JSX map render.
  return (
    <>
      <style jsx global>{`
        .secure-drive-scroll-host {
          scrollbar-width: none !important;
          -ms-overflow-style: none !important;
        }
        .secure-drive-scroll-host::-webkit-scrollbar {
          display: none !important;
          width: 0 !important;
          height: 0 !important;
        }
        .secure-drive-scroll-host::-webkit-scrollbar-button {
          display: none !important;
          width: 0 !important;
          height: 0 !important;
        }
      `}</style>
      <section
      className="relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background p-2 sm:p-3"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        hidden
        aria-label="Choose files to upload"
        onChange={(event) => {
          handleSelectedFiles(event.currentTarget.files);
          event.currentTarget.value = "";
        }}
      />
      <input
        ref={(input) => {
          folderInputRef.current = input;
          input?.setAttribute("webkitdirectory", "");
        }}
        type="file"
        multiple
        hidden
        aria-label="Choose a folder to upload"
        onChange={(event) => {
          handleSelectedFiles(event.currentTarget.files);
          event.currentTarget.value = "";
        }}
      />
      <div className="sticky top-0 z-40 bg-background pb-1 pt-1">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 px-1 pt-1 sm:px-2 sm:pt-2">
        <Breadcrumb
          items={folderPath}
          className="min-w-0 [&>ol]:text-lg [&>ol]:font-semibold sm:[&>ol]:text-xl"
          dropTargetIndex={breadcrumbDropTargetIndex}
          onItemDragOver={handleBreadcrumbDragOver}
          onItemDragLeave={handleBreadcrumbDragLeave}
          onItemDrop={handleBreadcrumbDrop}
        />

        <div className="flex shrink-0 items-center gap-1.5">
          <DriveNewMenu />
          <div className="flex items-center gap-0.5 rounded-xl border border-border bg-background p-0.5">
            <button
              type="button"
              onClick={() => setView("list")}
              className={`flex h-9 w-9 items-center justify-center rounded-[9px] border border-transparent transition-colors duration-(--motion-fast) ${view === "list" ? "bg-brand-soft text-brand-contrast" : "text-muted hover:bg-surface hover:text-foreground"}`}
              aria-label="List view"
              aria-pressed={view === "list"}
            >
              <List size={16} />
            </button>
            <button
              type="button"
              onClick={() => setView("grid")}
              className={`flex h-9 w-9 items-center justify-center rounded-[9px] border border-transparent transition-colors duration-(--motion-fast) ${view === "grid" ? "bg-brand-soft text-brand-contrast" : "text-muted hover:bg-surface hover:text-foreground"}`}
              aria-label="Grid view"
              aria-pressed={view === "grid"}
            >
              <Grid2x2 size={16} />
            </button>
          </div>
        </div>
      </div>
      {searchQuery && listView === "drive" && (
        <div className="mt-2 flex min-w-0 items-center gap-2 px-2 text-xs text-muted">
          <Search size={13} className="shrink-0" />
          <span className="truncate">Search results for <strong className="font-semibold text-foreground">“{searchQuery}”</strong></span>
          <button
            type="button"
            onClick={() => {
              router.push("/drive");
              window.dispatchEvent(new CustomEvent(DRIVE_SEARCH_CHANGED_EVENT, { detail: { query: "" } }));
            }}
            className="ml-auto shrink-0 rounded-md px-2 py-1 font-semibold text-brand-contrast hover:bg-brand-soft"
          >Clear search</button>
        </div>
      )}

      <DriveActionToolbar
        title={title}
        selectedItems={selectedItems}
        selectedCanManage={selectedCanManage}
        selectedCanShare={selectedCanShare}
        isMovingItems={isMovingItems}
        isDuplicatingItems={isDuplicatingItems}
        sortKey={sortKey}
        sortDirection={sortDirection}
        itemCount={driveItems.length}
        hasListView={Boolean(listView)}
        onClearSelection={() => { clearSelection(); }}
        onRestoreSelected={() => { void restoreItems(selectedItems); }}
        onRunAction={runAction}
        onToggleStarSelected={() => { void toggleStar(selectedItems); }}
        onPendingDelete={(action) => setPendingDestructive({ action, count: selectedItems.length, targets: selectedItems })}
        onSortKeyChange={setSortKey}
        onToggleSortDirection={() => setSortDirection((current) => (current === "asc" ? "desc" : "asc"))}
      />
      </div>

      {downloadStatus && (
        <div className="mb-3 flex min-h-10 items-center gap-3 rounded-xl border border-border bg-surface px-3 py-2 text-sm" role="status" aria-live="polite">
          <span>{downloadStatus.text}</span>
          {downloadStatus.progress && downloadStatus.progress.total !== null && (
            <progress
              className="ml-auto h-2 w-32 accent-brand"
              max={downloadStatus.progress.total}
              value={downloadStatus.progress.loaded}
              aria-label="Download progress"
            />
          )}
          <button type="button" className="ml-auto text-muted hover:text-foreground" onClick={() => setDownloadStatus(null)} aria-label="Dismiss download status">
            <X size={15} />
          </button>
        </div>
      )}

      <div className="relative min-h-0 min-w-0 flex-1" onPointerDownCapture={handleMarqueePointerDown}>
        <div
          id="drive-scroll-region"
          ref={driveListRef}
          className={`secure-drive-scroll-host absolute inset-0 min-h-0 min-w-0 overflow-auto overscroll-contain rounded-xl border-t bg-surface transition-colors duration-(--motion-fast) ${fileDropActive ? "border-brand-contrast ring-2 ring-brand-contrast/30" : "border-border"} ${marqueeActive ? "select-none cursor-crosshair touch-none" : ""}`}
        >
        {loading ? (
          <EmptyState title={`Loading ${title}`} description="Fetching items from your account…" />
        ) : loadError ? (
          <EmptyState title="Could not load your Drive" description={loadError} action={
            <Button variant="secondary" size="sm" onClick={() => listView && void loadItems(listView === "drive" ? currentFolderId : null, listView)}>Try again</Button>
          } />
        ) : sortedItems.length === 0 ? (
          <EmptyState
            title={searchQuery && listView === "drive" ? "No matching files or folders" : title === "Starred" ? "No starred items yet" : title === "Trash" ? "Trash is empty" : title === "Recent" ? "No recent items" : "No files here"}
            description={
              searchQuery && listView === "drive"
                ? "Try a different name or clear the search to browse this workspace."
                : title === "Starred"
                  ? "Files and folders you star will appear here."
                  : listView
                    ? title === "Recent"
                      ? "Files and folders you open or change will appear here."
                      : "Files and folders in this location will appear here."
                    : "Items will appear here when real Drive data is connected."
            }
            action={currentFolderId !== null ? (
              <Button variant="secondary" size="sm" onClick={() => router.push("/drive")}>
                Back to {title}
              </Button>
            ) : undefined}
          />
        ) : view === "list" ? (
          <DriveListTable
            items={sortedItems}
            selectedIds={selectedIds}
            sortKey={sortKey}
            sortDirection={sortDirection}
            onSort={(field) => {
              setSortKey(field);
              setSortDirection(sortKey === field && sortDirection === "asc" ? "desc" : "asc");
            }}
            onItemClick={handleItemClick}
            onOpen={openItem}
            onToggleStar={toggleStar}
            showStar={title !== "Trash"}
            createActions={createActions}
            onDragStart={handleDragStart}
            onDragEnd={() => { setFileDropActive(false); setDropTargetFolderId(null); }}
            onFolderDragOver={handleFolderDragOver}
            onDropOnFolder={handleDropOnFolder}
            dropTargetFolderId={dropTargetFolderId}
          />
        ) : (
          <DriveGrid
            folderItems={folderItems}
            fileItems={fileItems}
            selectedIds={selectedIds}
            title={title}
            dropTargetFolderId={dropTargetFolderId}
            onItemClick={handleItemClick}
            onOpen={openItem}
            onToggleItem={toggleItem}
            onToggleStar={toggleStar}
            createActions={createActions}
            onDragStart={handleDragStart}
            onDragEnd={() => { setFileDropActive(false); setDropTargetFolderId(null); }}
            onFolderDragOver={handleFolderDragOver}
            onDropOnFolder={handleDropOnFolder}
          />
        )}
        </div>
        {view === "list" && scrollMetrics.trackTop > 0 && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute right-0 top-0 z-20 w-2 border-b border-border bg-background"
            style={{ height: `${scrollMetrics.trackTop}px` }}
          />
        )}
        {maxScrollTop > 1 && scrollbarThumbHeight > 0 && (
          <div
            ref={scrollbarTrackRef}
            role="scrollbar"
            aria-label="Drive list vertical scrollbar"
            aria-controls="drive-scroll-region"
            aria-orientation="vertical"
            aria-valuemin={0}
            aria-valuemax={Math.round(maxScrollTop)}
            aria-valuenow={Math.round(scrollMetrics.scrollTop)}
            aria-valuetext={`${Math.round((scrollMetrics.scrollTop / maxScrollTop) * 100)}% scrolled`}
            tabIndex={0}
            data-no-marquee-selection="true"
            onPointerDown={handleScrollbarPointerDown}
            onPointerMove={handleScrollbarPointerMove}
            onPointerUp={finishScrollbarPointer}
            onPointerCancel={finishScrollbarPointer}
            onKeyDown={handleScrollbarKeyDown}
            className="absolute right-0 z-30 w-2 touch-none cursor-pointer rounded-full bg-transparent opacity-100 transition-opacity focus-visible:opacity-100 focus-visible:outline-none"
            style={{ top: `${scrollMetrics.trackTop}px`, bottom: "8px" }}
          >
            <div
              data-drive-scroll-thumb="true"
              className="absolute left-0 right-0 top-0 rounded-full bg-gray-400 transition-colors hover:bg-gray-500"
              style={{
                height: `${scrollbarThumbHeight}px`,
                transform: `translateY(${scrollbarThumbTop}px)`,
              }}
            />
          </div>
        )}
      </div>

      <DriveCreateFolderDialog
        open={isCreateFolderOpen}
        creating={isCreatingFolder}
        name={newFolderName}
        error={folderNameError}
        onNameChange={(name) => { setNewFolderName(name); setFolderNameError(""); }}
        onClose={() => setIsCreateFolderOpen(false)}
        onCreate={() => { void handleCreateFolder(); }}
      />

      <DriveMoveDialog
        open={isMoveDialogOpen}
        moving={isMovingItems}
        targetCount={moveTargets.length}
        details={moveDestinationDetails}
        items={moveDestinationItems}
        loading={moveDestinationLoading}
        error={moveDestinationError}
        destinationId={moveDestinationId}
        onClose={() => setIsMoveDialogOpen(false)}
        onLoadDestination={(id) => { void loadMoveDestination(id); }}
        onConfirm={() => { void confirmMoveItems(); }}
      />

      {toast && (
        <div className="fixed bottom-4 right-4 z-80 w-[min(24rem,calc(100vw-2rem))]">
          <Toast title={toastTitle} variant={toastVariant} onDismiss={() => setToast(null)}>
            {toast}
          </Toast>
        </div>
      )}

      {fileDropActive && (
        <div
          aria-live="polite"
          className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center rounded-xl border-2 border-dashed border-brand-contrast bg-brand-soft/70 p-4 text-center text-base font-semibold text-brand-contrast"
        >
          {dragMessage}
        </div>
      )}
      {selectionBox && (selectionBox.width > 2 || selectionBox.height > 2) && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed z-120 border border-brand-contrast bg-brand-soft/35 shadow-sm"
          style={{
            left: selectionBox.left,
            top: selectionBox.top,
            width: selectionBox.width,
            height: selectionBox.height,
          }}
        />
      )}

      <RenameDialog
        target={renameTarget}
        onClose={() => setRenameTarget(null)}
        onRenamed={handleRenamed}
      />
      <FilePreviewDialog
        file={previewTarget}
        onClose={() => setPreviewTarget(null)}
        onDownload={(file) => {
          setPreviewTarget(null);
          void downloadItems([{ id: file.id, name: file.name, type: "document" }]);
        }}
      />

      <ShareManagementDialog target={manageShareTarget} onClose={() => setManageShareTarget(null)}
        onChanged={() => { if (listView) void loadItems(listView === "drive" ? currentFolderId : null, listView); }} />

      <DriveShareDialog
        open={shareDialogOpen}
        targetCount={shareTargets.length}
        sharing={sharing}
        email={shareEmail}
        permission={sharePermission}
        onClose={() => setShareDialogOpen(false)}
        onEmailChange={setShareEmail}
        onPermissionChange={setSharePermission}
        onSubmit={(event) => { void submitShare(event); }}
      />

      <ConfirmDialog
        open={pendingDestructive !== null}
        title={pendingDestructive?.action === "delete" ? "Delete permanently?" : "Move to trash?"}
        description={
          pendingDestructive?.action === "delete"
            ? `Permanently delete ${pendingDestructive.count} item(s)? Their stored objects will be removed from storage. This cannot be undone.`
            : `Move ${pendingDestructive?.count ?? 1} item(s) to Trash? You can restore them later.`
        }
        confirmLabel={pendingDestructive?.action === "delete" ? "Delete permanently" : "Move to trash"}
        destructive
        onClose={() => setPendingDestructive(null)}
        onConfirm={() => {
          const pending = pendingDestructive;
          setPendingDestructive(null);
          if (pending) void applyDestructiveAction(pending);
        }}
      />
      </section>
    </>
  );
}

