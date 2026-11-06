"use client";

import { useRef, useState, type Dispatch, type DragEvent, type SetStateAction } from "react";
import { getDriveFolderDetails, getDriveItems, type DriveFolderDetails, type DriveListView } from "@/lib/drive-service";
import type { DriveItem } from "./types";
import {
  ITEM_DRAG_TYPE, executeMoveAndRefresh,
  getBreadcrumbMoveDestination, resolveDraggedDriveItems, serializeDraggedDriveItems,
} from "./drive-move-utils";

type Options = {
  title: string;
  listView: DriveListView | null;
  currentFolderId: number | null;
  folderDetails: DriveFolderDetails | null;
  driveItems: DriveItem[];
  selectedIds: Set<number>;
  selectedItems: DriveItem[];
  setFileDropActive: Dispatch<SetStateAction<boolean>>;
  clearSelectedIds: () => void;
  notifyFolderTreeChanged: () => void;
  loadItems: (folderId: number | null, view: DriveListView, queryOverride?: string) => Promise<void>;
  postItemAction: (path: string, targets: DriveItem[], extra?: Record<string, unknown>) => Promise<{ detail: string; count?: number }>;
  canManageItemsInDrive: (action: string) => boolean;
  setToast: (message: string | null) => void;
};

/**
 * Nhóm chức năng di chuyển Drive: chọn thư mục đích, Move qua dialog,
 * kéo thả vào thư mục hoặc breadcrumb. Không quản lý kéo tệp từ máy tính (Upload).
 */
export default function useDriveFileOperations({
  title, listView, currentFolderId, folderDetails, driveItems,
  selectedIds, selectedItems, setFileDropActive,
  clearSelectedIds, notifyFolderTreeChanged, loadItems,
  postItemAction, canManageItemsInDrive, setToast,
}: Options) {
  const moveDestinationRequestIdRef = useRef(0);
  const [isMoveDialogOpen, setIsMoveDialogOpen] = useState(false);
  const [moveTargets, setMoveTargets] = useState<DriveItem[]>([]);
  const [moveDestinationId, setMoveDestinationId] = useState<number | null>(null);
  const [moveDestinationItems, setMoveDestinationItems] = useState<DriveItem[]>([]);
  const [moveDestinationDetails, setMoveDestinationDetails] = useState<DriveFolderDetails | null>(null);
  const [moveDestinationLoading, setMoveDestinationLoading] = useState(false);
  const [moveDestinationError, setMoveDestinationError] = useState<string | null>(null);
  const [isMovingItems, setIsMovingItems] = useState(false);
  const [dropTargetFolderId, setDropTargetFolderId] = useState<number | null>(null);
  const [breadcrumbDropTargetIndex, setBreadcrumbDropTargetIndex] = useState<number | null>(null);

  async function loadMoveDestination(folderId: number | null) {
    const requestId = ++moveDestinationRequestIdRef.current;
    setMoveDestinationId(folderId);
    setMoveDestinationLoading(true);
    setMoveDestinationError(null);
    try {
      const [nextItems, details] = await Promise.all([
        getDriveItems(folderId, "drive"),
        folderId !== null ? getDriveFolderDetails(folderId) : Promise.resolve(null),
      ]);
      // Tránh việc phản hồi cũ ghi đè khi người dùng chuyển thư mục đích liên tiếp.
      if (requestId !== moveDestinationRequestIdRef.current) return;
      setMoveDestinationItems(nextItems.filter((candidate) => candidate.type === "folder"));
      setMoveDestinationDetails(details);
    } catch (error) {
      if (requestId !== moveDestinationRequestIdRef.current) return;
      setMoveDestinationError(error instanceof Error ? error.message : "Could not load destination folders.");
    } finally {
      if (requestId === moveDestinationRequestIdRef.current) setMoveDestinationLoading(false);
    }
  }

  function openMoveDialog(targets: DriveItem[]) {
    if (!targets.length) {
      setToast("Select at least one item to move.");
      return;
    }
    if (!canManageItemsInDrive("Move")) return;
    setMoveTargets(targets);
    setIsMoveDialogOpen(true);
    void loadMoveDestination(null);
  }

  // Cả menu Move và kéo thả đều dùng một endpoint và cùng trình tự làm mới danh sách.
  function refreshAfterMove() {
    return listView
      ? loadItems(listView === "drive" ? currentFolderId : null, listView)
      : Promise.resolve();
  }

  async function confirmMoveItems() {
    if (!moveTargets.length || isMovingItems) return;
    setIsMovingItems(true);
    try {
      await executeMoveAndRefresh(moveTargets, moveDestinationId, {
        postItemAction,
        onMoved: () => { setIsMoveDialogOpen(false); setMoveTargets([]); },
        clearSelectedIds, notifyFolderTreeChanged, refreshItems: refreshAfterMove,
      });
      // Move thành công chỉ làm mới danh sách; không thêm thông báo không cần thiết.
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not move selected items.");
    } finally {
      setIsMovingItems(false);
      setDropTargetFolderId(null);
    }
  }

  async function moveItemsToFolder(targets: DriveItem[], destinationFolderId: number | null) {
    if (!targets.length || isMovingItems) return;
    if (!canManageItemsInDrive("Move")) return;
    setIsMovingItems(true);
    setDropTargetFolderId(destinationFolderId);
    try {
      await executeMoveAndRefresh(targets, destinationFolderId, {
        postItemAction,
        clearSelectedIds, notifyFolderTreeChanged, refreshItems: refreshAfterMove,
      });
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not move selected items.");
    } finally {
      setIsMovingItems(false);
      setDropTargetFolderId(null);
    }
  }

  function breadcrumbDestinationId(index: number): number | null | undefined {
    return getBreadcrumbMoveDestination({
      title, listView, index,
      ancestorIds: (folderDetails?.ancestors ?? []).map((ancestor) => ancestor.id),
      currentFolderId,
    });
  }

  function handleBreadcrumbDragOver(event: DragEvent<HTMLElement>, index: number) {
    if (!Array.from(event.dataTransfer.types).includes(ITEM_DRAG_TYPE)) return;
    if (breadcrumbDestinationId(index) === undefined) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    setBreadcrumbDropTargetIndex(index);
  }

  function handleBreadcrumbDragLeave(event: DragEvent<HTMLElement>, index: number) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setBreadcrumbDropTargetIndex((current) => current === index ? null : current);
  }

  async function handleBreadcrumbDrop(event: DragEvent<HTMLElement>, index: number) {
    if (!Array.from(event.dataTransfer.types).includes(ITEM_DRAG_TYPE)) return;
    const destinationFolderId = breadcrumbDestinationId(index);
    if (destinationFolderId === undefined) return;

    event.preventDefault();
    event.stopPropagation();
    setBreadcrumbDropTargetIndex(null);
    try {
      const targets = resolveDraggedDriveItems(event.dataTransfer.getData(ITEM_DRAG_TYPE), driveItems);
      if (!targets.length) {
        setToast("Could not identify the dragged Drive items. Select them and try again.");
        return;
      }
      await moveItemsToFolder(targets, destinationFolderId);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not move the dragged items to this folder.");
    }
  }

  // Cuộn danh sách khi kéo sát mép để người dùng thả vào thư mục nằm ngoài vùng nhìn thấy.
  function autoScrollDuringInternalDrag(event: DragEvent<HTMLElement>) {
    const pointerY = event.clientY;
    const edgeSize = 92;
    const maxStep = 28;
    const getStep = (distanceIntoEdge: number) => {
      const progress = Math.max(0, Math.min(1, 1 - distanceIntoEdge / edgeSize));
      return Math.max(7, Math.ceil(maxStep * progress));
    };

    let node = event.target instanceof HTMLElement ? event.target : null;
    while (node && node !== document.documentElement) {
      const style = window.getComputedStyle(node);
      const canScrollY = /(auto|scroll|overlay)/.test(style.overflowY)
        && node.scrollHeight > node.clientHeight + 2;
      if (canScrollY) {
        const rect = node.getBoundingClientRect();
        const topDistance = pointerY - rect.top;
        const bottomDistance = rect.bottom - pointerY;
        if (topDistance >= 0 && topDistance < edgeSize && node.scrollTop > 0) {
          node.scrollTop = Math.max(0, node.scrollTop - getStep(topDistance));
          return;
        }
        if (
          bottomDistance >= 0
          && bottomDistance < edgeSize
          && node.scrollTop + node.clientHeight < node.scrollHeight - 1
        ) {
          node.scrollTop = Math.min(
            node.scrollHeight - node.clientHeight,
            node.scrollTop + getStep(bottomDistance),
          );
          return;
        }
      }
      node = node.parentElement;
    }

    // Nếu không có vùng cuộn riêng, sử dụng vùng cuộn trang.
    const pageScroller = document.scrollingElement as HTMLElement | null;
    if (!pageScroller) return;
    const viewportHeight = window.innerHeight;
    if (pointerY < edgeSize && pageScroller.scrollTop > 0) {
      window.scrollBy(0, -getStep(pointerY));
    } else if (
      pointerY > viewportHeight - edgeSize
      && pageScroller.scrollTop + viewportHeight < pageScroller.scrollHeight - 1
    ) {
      window.scrollBy(0, getStep(viewportHeight - pointerY));
    }
  }

  function handleDragStart(event: DragEvent<HTMLButtonElement>, item: DriveItem) {
    const targets = selectedIds.has(item.id) && selectedItems.length ? selectedItems : [item];
    event.dataTransfer.setData(ITEM_DRAG_TYPE, serializeDraggedDriveItems(targets));
    event.dataTransfer.effectAllowed = "move";
    setDropTargetFolderId(null);
  }

  function handleFolderDragOver(event: DragEvent<HTMLElement>, item: DriveItem) {
    if (item.type !== "folder" || !Array.from(event.dataTransfer.types).includes(ITEM_DRAG_TYPE)) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    autoScrollDuringInternalDrag(event);
    if (item.folderId) setDropTargetFolderId(item.folderId);
  }

  async function handleDropOnFolder(event: DragEvent<HTMLElement>, folder: DriveItem) {
    if (!Array.from(event.dataTransfer.types).includes(ITEM_DRAG_TYPE)) return;
    if (folder.type !== "folder" || !folder.folderId) return;
    event.preventDefault();
    event.stopPropagation();
    setFileDropActive(false);
    try {
      const targets = resolveDraggedDriveItems(event.dataTransfer.getData(ITEM_DRAG_TYPE), driveItems);
      if (!targets.length) {
        setToast("Could not identify the dragged Drive items. Select them and try again.");
        return;
      }
      await moveItemsToFolder(targets, folder.folderId);
    } catch {
      setToast("Could not read the dragged items. Use Move to choose a destination instead.");
    }
  }

  return {
    isMoveDialogOpen, setIsMoveDialogOpen, moveTargets,
    moveDestinationId, moveDestinationItems, moveDestinationDetails,
    moveDestinationLoading, moveDestinationError, isMovingItems,
    dropTargetFolderId, setDropTargetFolderId, breadcrumbDropTargetIndex,
    loadMoveDestination, openMoveDialog, confirmMoveItems,
    handleBreadcrumbDragOver, handleBreadcrumbDragLeave, handleBreadcrumbDrop,
    autoScrollDuringInternalDrag, handleDragStart, handleFolderDragOver, handleDropOnFolder,
  };
}
