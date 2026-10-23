"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Copy,
  Download,
  FileText,
  Folder,
  FolderOpen,
  Grid2x2,
  GripVertical,
  Image as ImageIcon,
  List,
  ListFilter,
  MoreHorizontal,
  Move,
  Pencil,
  Share2,
  Star,
  Trash2,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import Breadcrumb from "@/components/ui/Breadcrumb";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import ContextMenu, { type ContextMenuAction } from "@/components/ui/ContextMenu";
import EmptyState from "@/components/shared/EmptyState";
import Toast from "@/components/ui/Toast";
import DriveNewMenu, {
  DRIVE_CREATE_FOLDER_EVENT,
  DRIVE_UPLOAD_FILES_EVENT,
  DRIVE_UPLOAD_FOLDER_EVENT,
} from "@/components/drive/DriveNewMenu";
import { DRIVE_UPLOAD_COMPLETED_EVENT, useUploadManager } from "@/components/drive/UploadManager";
import {
  downloadDriveFile,
  getDriveFolderDetails,
  getDriveItems,
  type DriveFolderDetails,
  type DriveListView,
  type DownloadProgress,
} from "@/lib/drive-service";
import {
  accountCsrfHeaders,
  requestAccountApi,
} from "@/lib/account-service";
import { DRIVE_SEARCH_CHANGED_EVENT, FOLDER_TREE_REFRESH_EVENT, WORKSPACE_CHANGED_EVENT } from "@/lib/workspace-context";

type ViewMode = "list" | "grid";
type SortDirection = "asc" | "desc";
type SortKey = "name" | "modified" | "size" | "type";
type DriveItemType = "folder" | "document" | "image";
type PendingDestructiveAction = {
  action: "trash" | "delete";
  count: number;
  targets: DriveItem[];
};

type SelectionBox = {
  left: number;
  top: number;
  width: number;
  height: number;
};

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

const ITEM_DRAG_TYPE = "application/x-securedrive-item";

export type DriveItem = {
  id: number;
  folderId?: number;
  name: string;
  owner: string;
  ownerInitials: string;
  modified: string;
  size: string;
  type: DriveItemType;
  starred?: boolean;
  canManage?: boolean;
};

type DriveFileBrowserProps = {
  title: string;
  items: DriveItem[];
};

const MAX_UPLOAD_FILES_PER_BATCH = 500;
const MAX_UPLOAD_FILE_SIZE = 100 * 1024 * 1024;
const MAX_UPLOAD_PATH_LENGTH = 1024;
const MAX_FILE_NAME_LENGTH = 255;

function listViewForTitle(title: string): DriveListView | null {
  if (title === "My Drive") return "drive";
  if (title === "Recent") return "recent";
  if (title === "Trash") return "trash";
  if (title === "Shared with me") return "shared";
  if (title === "Starred") return "starred";
  return null;
}

function renderItemIcon(type: DriveItemType, size: number): ReactNode {
  if (type === "folder") return <Folder size={size} />;
  if (type === "image") return <ImageIcon size={size} />;
  return <FileText size={size} />;
}

type DroppedEntry = {
  name: string;
  fullPath: string;
  isFile: boolean;
  isDirectory: boolean;
  file?: (success: (file: File) => void, failure: (error: DOMException) => void) => void;
  createReader?: () => {
    readEntries: (
      success: (entries: DroppedEntry[]) => void,
      failure: (error: DOMException) => void,
    ) => void;
  };
};

function getDroppedEntry(item: DataTransferItem): DroppedEntry | null {
  const itemWithEntry = item as DataTransferItem & {
    webkitGetAsEntry?: () => DroppedEntry | null;
  };
  return itemWithEntry.webkitGetAsEntry?.() ?? null;
}

async function readDroppedEntry(entry: DroppedEntry): Promise<{ file: File; relativePath: string }[]> {
  if (entry.isFile && entry.file) {
    const file = await new Promise<File>((resolve, reject) => {
      entry.file?.(resolve, reject);
    });
    return [{ file, relativePath: entry.fullPath.replace(/^\/+/, "") || file.name }];
  }

  if (entry.isDirectory && entry.createReader) {
    const reader = entry.createReader();
    const children: DroppedEntry[] = [];
    while (true) {
      const batch = await new Promise<DroppedEntry[]>((resolve, reject) => {
        reader.readEntries(resolve, reject);
      });
      if (batch.length === 0) break;
      children.push(...batch);
    }
    const nested = await Promise.all(children.map(readDroppedEntry));
    return nested.flat();
  }

  throw new Error(`The browser couldn't read "${entry.name}". Check folder access or choose files instead.`);
}

function validateUploadPath(path: string, file: File): string | null {
  const segments = path.split(/[\\/]/);
  if (!path.trim() || path.length > MAX_UPLOAD_PATH_LENGTH) return "File path is empty or exceeds 1,024 characters.";
  if (segments.some((segment) => !segment || segment === "." || segment === "..")) return "File path contains an invalid path segment.";
  if (file.name.length > MAX_FILE_NAME_LENGTH) return "File name exceeds 255 characters.";
  if (/[<>:"|?*\u0000-\u001f]/.test(file.name)) return "File name contains characters that are not allowed.";
  if (file.size > MAX_UPLOAD_FILE_SIZE) return "File exceeds the current 100 MB upload limit.";
  return null;
}

function parseSize(value: string) {
  const match = value.match(/^([\d.]+)\s*(B|KB|MB|GB|TB)$/i);
  if (!match) return 0;
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unitIndex = units.indexOf(match[2].toUpperCase());
  return Number(match[1]) * 1024 ** unitIndex;
}

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
  const [driveItems, setDriveItems] = useState(items);
  const [searchQuery, setSearchQuery] = useState("");
  const searchQueryRef = useRef("");
  const [loading, setLoading] = useState(listView !== null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [folderDetails, setFolderDetails] = useState<DriveFolderDetails | null>(null);
  const [view, setView] = useState<ViewMode>("list");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());
  const [isCreateFolderOpen, setIsCreateFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("Untitled folder");
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const [folderNameError, setFolderNameError] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const [downloadStatus, setDownloadStatus] = useState<{
    text: string;
    progress: DownloadProgress | null;
  } | null>(null);
  const [pendingDestructive, setPendingDestructive] = useState<PendingDestructiveAction | null>(null);
  const [shareDialogOpen, setShareDialogOpen] = useState(false);
  const [shareTargets, setShareTargets] = useState<DriveItem[]>([]);
  const [shareEmail, setShareEmail] = useState("");
  const [sharePermission, setSharePermission] = useState<"viewer" | "editor">("viewer");
  const [sharing, setSharing] = useState(false);
  // Only OS/browser file drags activate the upload overlay. Internal Drive drags
  // must never wash out the whole interface.
  const [fileDropActive, setFileDropActive] = useState(false);
  const [dragMessage, setDragMessage] = useState("Drop files to upload");
  const [marqueeActive, setMarqueeActive] = useState(false);
  const [selectionBox, setSelectionBox] = useState<SelectionBox | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const driveListRef = useRef<HTMLDivElement>(null);
  const scrollbarTrackRef = useRef<HTMLDivElement>(null);
  const scrollbarDragRef = useRef<ScrollbarDrag>(null);
  const [scrollMetrics, setScrollMetrics] = useState<ScrollMetrics>({
    scrollTop: 0,
    clientHeight: 0,
    scrollHeight: 0,
    trackTop: 0,
  });
  const [selectionAnchorId, setSelectionAnchorId] = useState<number | null>(null);
  const selectionStartRef = useRef<{
    x: number;
    y: number;
    pointerId: number;
    additive: boolean;
    baseIds: Set<number>;
    dragged: boolean;
  } | null>(null);
  const marqueeSelectedIdsRef = useRef<Set<number>>(new Set());
  const loadRequestIdRef = useRef(0);
  const moveDestinationRequestIdRef = useRef(0);
  const pasteHandlerRef = useRef<(files: readonly { file: File; relativePath: string }[]) => void>(() => {});
  const [isMoveDialogOpen, setIsMoveDialogOpen] = useState(false);
  const [moveTargets, setMoveTargets] = useState<DriveItem[]>([]);
  const [moveDestinationId, setMoveDestinationId] = useState<number | null>(null);
  const [moveDestinationItems, setMoveDestinationItems] = useState<DriveItem[]>([]);
  const [moveDestinationDetails, setMoveDestinationDetails] = useState<DriveFolderDetails | null>(null);
  const [moveDestinationLoading, setMoveDestinationLoading] = useState(false);
  const [moveDestinationError, setMoveDestinationError] = useState<string | null>(null);
  const [isMovingItems, setIsMovingItems] = useState(false);
  const [isDuplicatingItems, setIsDuplicatingItems] = useState(false);
  const [dropTargetFolderId, setDropTargetFolderId] = useState<number | null>(null);
  const [breadcrumbDropTargetIndex, setBreadcrumbDropTargetIndex] = useState<number | null>(null);
  const { enqueue, openManager } = useUploadManager();

  const loadItems = useCallback(async (
    folderId: number | null,
    view: DriveListView,
    queryOverride?: string,
  ) => {
    const requestId = ++loadRequestIdRef.current;
    const query = view === "drive"
      ? (queryOverride ?? searchQueryRef.current).trim().slice(0, 255)
      : "";
    const effectiveFolderId = query ? null : folderId;
    setLoading(true);
    setLoadError(null);
    try {
      if (view === "drive" && effectiveFolderId !== null) {
        setFolderDetails(null);
        const [details, nextItems] = await Promise.all([
          getDriveFolderDetails(effectiveFolderId),
          getDriveItems(effectiveFolderId, view, query),
        ]);
        if (requestId !== loadRequestIdRef.current) return;
        setFolderDetails(details);
        setDriveItems(nextItems);
      } else {
        const nextItems = await getDriveItems(effectiveFolderId, view, query);
        if (requestId !== loadRequestIdRef.current) return;
        setFolderDetails(null);
        setDriveItems(nextItems);
      }
    } catch (error) {
      if (requestId !== loadRequestIdRef.current) return;
      setFolderDetails(null);
      setLoadError(error instanceof Error ? error.message : "Could not load Drive items.");
    } finally {
      if (requestId === loadRequestIdRef.current) setLoading(false);
    }
  }, []);

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
  }, [listView, currentFolderId, loadItems]);

  useEffect(() => {
    const handleSearchChanged = (event: Event) => {
      const customEvent = event as CustomEvent<{ query?: string }>;
      const query = (customEvent.detail?.query ?? "").trim().slice(0, 255);
      searchQueryRef.current = query;
      setSearchQuery(query);
      setSelectedIds(new Set());
      setSelectionAnchorId(null);
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
      setSelectedIds(new Set());
      setSelectionAnchorId(null);
      if (listView === "drive") void loadItems(query ? null : currentFolderId, "drive", query);
    };
    window.addEventListener(DRIVE_SEARCH_CHANGED_EVENT, handleSearchChanged);
    window.addEventListener("popstate", handleHistoryNavigation);
    return () => {
      window.removeEventListener(DRIVE_SEARCH_CHANGED_EVENT, handleSearchChanged);
      window.removeEventListener("popstate", handleHistoryNavigation);
    };
  }, [currentFolderId, listView, loadItems]);

  useEffect(() => {
    function handleWorkspaceChanged() {
      searchQueryRef.current = "";
      setSearchQuery("");
      setSelectedIds(new Set());
      setSelectionAnchorId(null);
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
  }, [currentFolderId, listView, loadItems, router]);

  useEffect(() => {
    function handleUploadCompleted(event: Event) {
      const detail = (event as CustomEvent<{ destinationId: string | null }>).detail;
      if (!detail || !listView) return;

      // Quota and the sidebar folder tree are cached summaries. Invalidate them
      // after every completed upload, even when the upload target is elsewhere.
      window.dispatchEvent(new Event(FOLDER_TREE_REFRESH_EVENT));
      if (listView === "drive") {
        const currentDestinationId = currentFolderId === null ? null : String(currentFolderId);
        if (detail.destinationId !== currentDestinationId) return;
        void loadItems(currentFolderId, "drive");
        return;
      }

      // Newly uploaded files can appear immediately in Recent as well.
      if (listView === "recent") {
        void loadItems(null, "recent");
      }
    }

    window.addEventListener(DRIVE_UPLOAD_COMPLETED_EVENT, handleUploadCompleted);
    return () => window.removeEventListener(DRIVE_UPLOAD_COMPLETED_EVENT, handleUploadCompleted);
  }, [currentFolderId, listView, loadItems]);

  const selectedItems = useMemo(
    () => driveItems.filter((item) => selectedIds.has(item.id)),
    [driveItems, selectedIds],
  );
  const selectedCanManage = selectedItems.length > 0 && selectedItems.every((item) => item.canManage !== false);
  const sortedItems = useMemo(
    () =>
      [...driveItems].sort((first, second) => {
        // Keep folders grouped before files, regardless of sort column/direction.
        const firstIsFolder = first.type === "folder";
        const secondIsFolder = second.type === "folder";
        if (firstIsFolder !== secondIsFolder) return firstIsFolder ? -1 : 1;

        let comparison: number;
        if (sortKey === "modified") {
          comparison = first.modified.localeCompare(second.modified, undefined, { numeric: true });
        } else if (sortKey === "size") {
          comparison = parseSize(first.size) - parseSize(second.size);
        } else if (sortKey === "type") {
          comparison = first.type.localeCompare(second.type);
        } else {
          comparison = first.name.localeCompare(second.name, undefined, { numeric: true });
        }
        return sortDirection === "asc" ? comparison : -comparison;
      }),
    [driveItems, sortDirection, sortKey],
  );
  const folderItems = useMemo(
    () => sortedItems.filter((item) => item.type === "folder"),
    [sortedItems],
  );
  const fileItems = useMemo(
    () => sortedItems.filter((item) => item.type !== "folder"),
    [sortedItems],
  );

  const addUploadFiles = useCallback(async (files: readonly { file: File; relativePath: string }[]) => {
    if (files.length === 0) {
      setToast("No files were provided by the browser. Folder access may have been denied.");
      return;
    }
    if (files.length > MAX_UPLOAD_FILES_PER_BATCH) {
      setToast(`A batch can contain at most ${MAX_UPLOAD_FILES_PER_BATCH} files. None of this selection was added.`);
      return;
    }

    const baseDestinationId = currentFolderId !== null ? String(currentFolderId) : null;
    const normalizedFiles = files.map(({ file, relativePath }) => {
      const normalizedPath = relativePath.replace(/\\/g, "/").replace(/^\/+/, "");
      return {
        file,
        relativePath: normalizedPath,
        validationError: validateUploadPath(normalizedPath, file),
      };
    });

    // Folder paths shown in the queue must correspond to real Folder rows. Resolve each
    // parent path first, then attach that folder's ID to the individual upload task.
    const folderIdsByPath = new Map<string, string>();
    const createdOrReusedFolderIds = new Set<string>();
    const ensureFolder = async (name: string, parentId: string | null): Promise<string> => {
      const cacheKey = `${parentId ?? "root"}::${name.toLocaleLowerCase()}`;
      const cached = folderIdsByPath.get(cacheKey);
      if (cached) return cached;

      // Reuse a same-named folder if it already exists under this parent.
      const siblings = await getDriveItems(parentId === null ? null : Number(parentId), "drive");
      const existing = siblings.find((item) =>
        item.type === "folder" && item.name.localeCompare(name, undefined, { sensitivity: "accent" }) === 0,
      );
      if (existing) {
        const id = String(existing.folderId ?? existing.id);
        folderIdsByPath.set(cacheKey, id);
        return id;
      }

      const created = await requestAccountApi<{
        id: number;
        name: string;
        parent_id: number | null;
        type: "folder";
      }>("/drive/api/folders/", {
        method: "POST",
        headers: await accountCsrfHeaders(),
        body: JSON.stringify({ name, parent_id: parentId === null ? null : Number(parentId) }),
      });
      const id = String(created.id);
      folderIdsByPath.set(cacheKey, id);
      createdOrReusedFolderIds.add(id);
      return id;
    };

    try {
      const queuedFiles: Array<typeof normalizedFiles[number] & { destinationId: string | null }> = [];
      // Resolve paths sequentially so two files sharing a new parent folder cannot race
      // and create duplicate folder rows before the in-memory cache is populated.
      for (const entry of normalizedFiles) {
        // Invalid entries remain visible as failed/invalid queue items but must not cause
        // folder creation with unsafe path segments.
        if (entry.validationError) {
          queuedFiles.push({ ...entry, destinationId: baseDestinationId });
          continue;
        }

        const segments = entry.relativePath.split("/");
        let destinationId = baseDestinationId;
        const directorySegments = segments.slice(0, -1);
        for (const segment of directorySegments) {
          if (!segment || segment === "." || segment === "..") {
            throw new Error(`Invalid folder path in "${entry.relativePath}". No upload tasks were added.`);
          }
          destinationId = await ensureFolder(segment, destinationId);
        }
        queuedFiles.push({ ...entry, destinationId });
      }

      enqueue(queuedFiles.map(({ file, relativePath, validationError, destinationId }) => ({
        file,
        relativePath,
        validationError,
        destinationId,
      })), baseDestinationId);
      if (createdOrReusedFolderIds.size > 0) {
        notifyFolderTreeChanged();
        if (listView === "drive") await loadItems(currentFolderId, "drive");
      }
      openManager();
    } catch (error) {
      setToast(error instanceof Error
        ? `Could not prepare the folder structure. No files were queued. ${error.message}`
        : "Could not prepare the folder structure. No files were queued.");
    }
  }, [currentFolderId, enqueue, listView, loadItems, openManager]);

  function handleSelectedFiles(fileList: FileList | null) {
    if (!fileList) return;
    const selected = Array.from(fileList).map((file) => ({
      file,
      relativePath: file.webkitRelativePath || file.name,
    }));
    void addUploadFiles(selected);
  }

  function openFolderPicker() {
    const input = folderInputRef.current;
    if (!input) return;
    if (!("webkitdirectory" in input)) {
      setToast("Folder selection isn't supported by this browser. Use Upload files and select files individually.");
      return;
    }
    input.click();
  }

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

  useEffect(() => {
    function onUploadFiles() {
      fileInputRef.current?.click();
    }
    function onUploadFolder() {
      openFolderPicker();
    }
    function onCreateFolder() {
      if (title !== "My Drive") {
        setToast("Creating folders is only available in My Drive.");
        return;
      }

      setNewFolderName("Untitled folder");
      setFolderNameError("");
      setIsCreateFolderOpen(true);
    }
    function onFilePickerCancel() {
      setToast("File selection canceled. Nothing was added to the queue.");
    }

    window.addEventListener(DRIVE_UPLOAD_FILES_EVENT, onUploadFiles);
    window.addEventListener(DRIVE_UPLOAD_FOLDER_EVENT, onUploadFolder);
    window.addEventListener(DRIVE_CREATE_FOLDER_EVENT, onCreateFolder);
    const fileInput = fileInputRef.current;
    const folderInput = folderInputRef.current;
    fileInput?.addEventListener("cancel", onFilePickerCancel);
    folderInput?.addEventListener("cancel", onFilePickerCancel);
    return () => {
      window.removeEventListener(DRIVE_UPLOAD_FILES_EVENT, onUploadFiles);
      window.removeEventListener(DRIVE_UPLOAD_FOLDER_EVENT, onUploadFolder);
      window.removeEventListener(DRIVE_CREATE_FOLDER_EVENT, onCreateFolder);
      fileInput?.removeEventListener("cancel", onFilePickerCancel);
      folderInput?.removeEventListener("cancel", onFilePickerCancel);
    };
  }, [title]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (
        event.target instanceof Element
        && event.target.closest('[role="menu"], dialog[open]')
      ) return;
      setSelectedIds(new Set());
      setSelectionAnchorId(null);
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  function handleItemClick(event: React.MouseEvent<HTMLElement>, id: number) {
    // Suppress the synthetic click after a marquee gesture using the clicked item DOM node.
    // This keeps render-time callback analysis free of ref reads.
    const clickedNode = event.currentTarget;
    if (clickedNode.dataset.suppressSelectionClick === "true") {
      delete clickedNode.dataset.suppressSelectionClick;
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    // Windows Explorer-style selection:
    // click = single select, Ctrl/Cmd+click = toggle one item, Shift+click = range.
    if (event.shiftKey) {
      event.preventDefault();
      const anchorId = selectionAnchorId ?? id;
      if (selectionAnchorId === null) setSelectionAnchorId(anchorId);
      let anchorIndex = sortedItems.findIndex((item) => item.id === anchorId);
      const targetIndex = sortedItems.findIndex((item) => item.id === id);
      if (anchorIndex < 0) anchorIndex = targetIndex;
      if (targetIndex < 0) return;

      const start = Math.min(anchorIndex, targetIndex);
      const end = Math.max(anchorIndex, targetIndex);
      const rangeIds = sortedItems.slice(start, end + 1).map((item) => item.id);
      setSelectedIds((current) => {
        const next = event.ctrlKey || event.metaKey ? new Set(current) : new Set<number>();
        rangeIds.forEach((rangeId) => next.add(rangeId));
        return next;
      });
      return;
    }

    if (event.ctrlKey || event.metaKey) {
      setSelectedIds((current) => {
        const next = new Set(current);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
      setSelectionAnchorId(id);
      return;
    }

    setSelectedIds(new Set([id]));
    setSelectionAnchorId(id);
  }

  function toggleItem(id: number) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setSelectionAnchorId(id);
  }

  function handleMarqueePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || event.shiftKey) return;
    const target = event.target;
    if (!(target instanceof Element)) return;
    // Starting on a row/card body is allowed: a simple click still selects that item,
    // while moving beyond the drag threshold turns the gesture into a marquee.
    // Keep menus, action buttons, sort controls, and explicit drag handles independent.
    if (target.closest(
      'thead, button, a, input, select, textarea, [role="menu"], [role="toolbar"], dialog[open], [contenteditable="true"], [data-no-marquee-selection="true"]',
    )) return;

    const additive = event.ctrlKey || event.metaKey;
    const baseIds = new Set(selectedIds);
    selectionStartRef.current = {
      x: event.clientX,
      y: event.clientY,
      pointerId: event.pointerId,
      additive,
      baseIds,
      dragged: false,
    };
    marqueeSelectedIdsRef.current = new Set(additive ? baseIds : []);
    setSelectionBox(null);
    setMarqueeActive(true);
  }

  useEffect(() => {
    function handlePointerMove(event: PointerEvent) {
      const start = selectionStartRef.current;
      const container = driveListRef.current;
      if (!start || !container || event.pointerId !== start.pointerId) return;

      const dx = event.clientX - start.x;
      const dy = event.clientY - start.y;
      if (!start.dragged && Math.hypot(dx, dy) < 4) return;
      start.dragged = true;

      const left = Math.min(start.x, event.clientX);
      const top = Math.min(start.y, event.clientY);
      const right = Math.max(start.x, event.clientX);
      const bottom = Math.max(start.y, event.clientY);
      setSelectionBox({ left, top, width: right - left, height: bottom - top });

      const next = new Set(start.additive ? start.baseIds : []);
      const itemNodes = container.querySelectorAll<HTMLElement>("[data-drive-item-id]");
      itemNodes.forEach((node) => {
        const rect = node.getBoundingClientRect();
        const intersects = rect.left <= right
          && rect.right >= left
          && rect.top <= bottom
          && rect.bottom >= top;
        if (intersects) {
          const id = Number(node.dataset.driveItemId);
          if (Number.isSafeInteger(id)) next.add(id);
        }
      });
      marqueeSelectedIdsRef.current = next;
      setSelectedIds(next);
    }

    function finishPointer(event: PointerEvent) {
      const start = selectionStartRef.current;
      if (!start || (event.pointerId !== undefined && event.pointerId !== start.pointerId)) return;
      if (start.dragged) {
        // Mark the item under the pointer so its synthetic post-drag click is ignored.
        // The marker is stored on the DOM item rather than a ref read by the render callback.
        const pointerTarget = event.target instanceof Element
          ? event.target.closest<HTMLElement>("[data-drive-item-id]")
          : null;
        if (pointerTarget) {
          pointerTarget.dataset.suppressSelectionClick = "true";
          window.setTimeout(() => {
            if (pointerTarget.dataset.suppressSelectionClick === "true") {
              delete pointerTarget.dataset.suppressSelectionClick;
            }
          }, 0);
        }
        const container = driveListRef.current;
        const selectedInListOrder = container
          ? Array.from(container.querySelectorAll<HTMLElement>("[data-drive-item-id]"))
            .map((node) => Number(node.dataset.driveItemId))
            .filter((id) => Number.isSafeInteger(id) && marqueeSelectedIdsRef.current.has(id))
          : [];
        if (selectedInListOrder.length) {
          setSelectionAnchorId(selectedInListOrder[selectedInListOrder.length - 1]);
        }
      } else if (!start.additive) {
        // Clicking blank space clears selection; a row/card click handler will then
        // select the clicked item if the pointer was released on one.
        const target = event.target;
        const clickedItem = target instanceof Element && target.closest('[data-drive-item-id]');
        if (!clickedItem) {
          setSelectedIds(new Set());
          setSelectionAnchorId(null);
        }
      }
      selectionStartRef.current = null;
      setSelectionBox(null);
      setMarqueeActive(false);
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", finishPointer);
    window.addEventListener("pointercancel", finishPointer);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", finishPointer);
      window.removeEventListener("pointercancel", finishPointer);
    };
  }, []);

  // Keep the latest queue handler available to the global paste listener without
  // reinstalling the listener on every render.
  useEffect(() => {
    pasteHandlerRef.current = addUploadFiles;
  }, [addUploadFiles]);

  useEffect(() => {
    function onPaste(event: ClipboardEvent) {
      const target = event.target;
      if (target instanceof Element && target.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]')) {
        return;
      }
      const transfer = event.clipboardData;
      if (!transfer) return;
      const fromFiles = Array.from(transfer.files ?? []);
      const fromItems = Array.from(transfer.items ?? [])
        .filter((item) => item.kind === "file")
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null);
      // The FileList is the canonical collection. Some browsers expose the same
      // clipboard payload through both properties; do not double-enqueue it.
      const files = fromFiles.length ? fromFiles : fromItems;
      // Do not interfere with normal text paste if the browser doesn't expose files.
      if (!files.length) return;
      event.preventDefault();
      pasteHandlerRef.current(files.map((file) => ({ file, relativePath: file.name })));
      setToast(`${files.length} file${files.length === 1 ? "" : "s"} pasted from clipboard and added to uploads.`);
    }

    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  function showNotConnected(action: string) {
    setToast(`${action} isn't connected yet. No files were changed.`);
  }

  function notifyFolderTreeChanged() {
    window.dispatchEvent(new Event(FOLDER_TREE_REFRESH_EVENT));
  }

  function openItem(item: DriveItem) {
    if (item.type !== "folder") {
      showNotConnected("Opening files");
      return;
    }
    if (!Number.isSafeInteger(item.folderId) || !item.folderId || item.folderId <= 0) {
      setToast("This folder has an invalid ID and cannot be opened.");
      return;
    }
    setSelectedIds(new Set());
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

  async function confirmMoveItems() {
    if (!moveTargets.length || isMovingItems) return;
    setIsMovingItems(true);
    try {
      await postItemAction("/drive/api/items/move/", moveTargets, {
        destination_folder_id: moveDestinationId,
      });
      setIsMoveDialogOpen(false);
      setMoveTargets([]);
      setSelectedIds(new Set());
      notifyFolderTreeChanged();
      if (listView) await loadItems(listView === "drive" ? currentFolderId : null, listView);
      // Successful moves refresh the list silently; keep error notifications below.
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
      await postItemAction("/drive/api/items/move/", targets, {
        destination_folder_id: destinationFolderId,
      });
      setSelectedIds(new Set());
      notifyFolderTreeChanged();
      if (listView) await loadItems(listView === "drive" ? currentFolderId : null, listView);
      // Successful drag-and-drop moves refresh the list silently.
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not move selected items.");
    } finally {
      setIsMovingItems(false);
      setDropTargetFolderId(null);
    }
  }

  function getBreadcrumbDestinationId(index: number): number | null | undefined {
    // Breadcrumb move targets are enabled only while browsing My Drive.
    if (title !== "My Drive" || listView !== "drive") return undefined;
    if (index === 0) return null; // My Drive root

    const ancestors = folderDetails?.ancestors ?? [];
    if (index >= 1 && index <= ancestors.length) {
      return ancestors[index - 1]?.id;
    }

    // The final crumb represents the folder currently open.
    if (index === ancestors.length + 1 && currentFolderId !== null) {
      return currentFolderId;
    }
    return undefined;
  }

  function handleBreadcrumbDragOver(event: React.DragEvent<HTMLElement>, index: number) {
    if (!Array.from(event.dataTransfer.types).includes(ITEM_DRAG_TYPE)) return;
    if (getBreadcrumbDestinationId(index) === undefined) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    setBreadcrumbDropTargetIndex(index);
  }

  function handleBreadcrumbDragLeave(event: React.DragEvent<HTMLElement>, index: number) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setBreadcrumbDropTargetIndex((current) => current === index ? null : current);
  }

  async function handleBreadcrumbDrop(event: React.DragEvent<HTMLElement>, index: number) {
    if (!Array.from(event.dataTransfer.types).includes(ITEM_DRAG_TYPE)) return;
    const destinationFolderId = getBreadcrumbDestinationId(index);
    if (destinationFolderId === undefined) return;

    event.preventDefault();
    event.stopPropagation();
    setBreadcrumbDropTargetIndex(null);
    try {
      const raw = event.dataTransfer.getData(ITEM_DRAG_TYPE);
      const parsed = JSON.parse(raw) as {
        items?: Array<{ id: number; type: DriveItemType; folderId?: number | null }>;
      };
      const targets = (parsed.items ?? [])
        .map((entry) => driveItems.find((candidate) => candidate.id === entry.id))
        .filter((candidate): candidate is DriveItem => candidate !== undefined);
      if (!targets.length) {
        setToast("Could not identify the dragged Drive items. Select them and try again.");
        return;
      }
      await moveItemsToFolder(targets, destinationFolderId);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not move the dragged items to this folder.");
    }
  }

  async function duplicateItems(targets: DriveItem[]) {
    if (!targets.length || isDuplicatingItems) return;
    if (!canManageItemsInDrive("Duplicate")) return;
    setIsDuplicatingItems(true);
    try {
      const result = await postItemAction("/drive/api/items/duplicate/", targets);
      setSelectedIds(new Set());
      notifyFolderTreeChanged();
      if (listView) await loadItems(listView === "drive" ? currentFolderId : null, listView);
      setToast(result.detail || "Duplicate created successfully.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not duplicate selected items.");
    } finally {
      setIsDuplicatingItems(false);
    }
  }

  async function restoreItems(targets: DriveItem[]) {
    if (!targets.length) return;
    try {
      const result = await postItemAction("/drive/api/items/restore/", targets);
      setSelectedIds(new Set());
      notifyFolderTreeChanged();
      if (listView) await loadItems(listView === "drive" ? currentFolderId : null, listView);
      setToast(result.detail || "Items restored successfully.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not restore selected items.");
    }
  }

  async function applyDestructiveAction(pending: PendingDestructiveAction) {
    const path = pending.action === "trash"
      ? "/drive/api/items/trash/"
      : "/drive/api/items/delete/";
    try {
      const result = await postItemAction(path, pending.targets);
      setSelectedIds(new Set());
      setSelectionAnchorId(null);
      notifyFolderTreeChanged();
      if (listView) await loadItems(listView === "drive" ? currentFolderId : null, listView);
      setToast(result.detail || (pending.action === "trash" ? "Moved to Trash." : "Permanently deleted."));
    } catch (error) {
      setToast(error instanceof Error ? error.message : "The file operation failed. No success was reported.");
    }
  }

  async function toggleStar(targets: DriveItem[], desired?: boolean) {
    if (!targets.length) return;
    const shouldStar = desired ?? !targets.every((item) => item.starred);
    try {
      const result = await postItemAction("/drive/api/items/star/", targets, { starred: shouldStar });
      setDriveItems((current) => current.map((item) => {
        const target = targets.some((selected) => selected.id === item.id && selected.type === item.type);
        return target ? { ...item, starred: shouldStar } : item;
      }));
      setSelectedIds(new Set());
      if (listView && listView !== "drive") {
        await loadItems(null, listView);
      }
      setToast(result.detail || (shouldStar ? "Added to Starred." : "Removed from Starred."));
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not update Starred.");
    }
  }

  function openShareDialog(targets: DriveItem[]) {
    if (!targets.length) {
      setToast("Select at least one item to share.");
      return;
    }
    if (!canManageItemsInDrive("Share")) return;
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

  async function downloadItems(targets: DriveItem[]) {
    const files = targets.filter((target) => target.type !== "folder");
    if (!files.length) {
      setDownloadStatus({ text: "Failed: select a file to download.", progress: null });
      return;
    }
    if (files.length !== targets.length) {
      setToast("Folders are not downloadable here. Downloading the selected files only.");
    }
    for (const file of files) {
      setDownloadStatus({ text: `Preparing ${file.name}`, progress: null });
      try {
        let latestProgress: DownloadProgress | null = null;
        await downloadDriveFile(file.id, file.name, ({ loaded, total }) => {
          latestProgress = { loaded, total };
          const amount = total ? ` ${Math.round((loaded / total) * 100)}%` : "";
          setDownloadStatus({
            text: `Downloading ${file.name}${amount}`,
            progress: latestProgress,
          });
        });
        setDownloadStatus({
          text: `Completed: ${file.name} received; browser save started.`,
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
    if (canManageTargets && title !== "Shared with me" && title !== "Trash") {
      actions.push({ label: "Share", onSelect: () => runAction("Share", item) });
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

  // Scroll the active Drive scroll container while an internal item is being dragged
  // near its top/bottom edge. This lets users drag from the end of a long list to folders above.
  function autoScrollDuringInternalDrag(event: React.DragEvent<HTMLElement>) {
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

    // Fall back to the document viewport when the page itself is the scroll container.
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

  function handleDragStart(event: React.DragEvent<HTMLButtonElement>, item: DriveItem) {
    const targets = selectedIds.has(item.id) && selectedItems.length ? selectedItems : [item];
    event.dataTransfer.setData(ITEM_DRAG_TYPE, JSON.stringify({
      items: targets.map((target) => ({
        id: target.id,
        type: target.type,
        folderId: target.folderId ?? null,
      })),
    }));
    event.dataTransfer.effectAllowed = "move";
    setDropTargetFolderId(null);
    // Internal Drive drags are never upload overlays.
  }

  function handleFolderDragOver(event: React.DragEvent<HTMLElement>, item: DriveItem) {
    if (item.type !== "folder" || !Array.from(event.dataTransfer.types).includes(ITEM_DRAG_TYPE)) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    autoScrollDuringInternalDrag(event);
    if (item.folderId) setDropTargetFolderId(item.folderId);
  }

  async function handleDropOnFolder(event: React.DragEvent<HTMLElement>, folder: DriveItem) {
    if (!Array.from(event.dataTransfer.types).includes(ITEM_DRAG_TYPE)) return;
    if (folder.type !== "folder" || !folder.folderId) return;
    event.preventDefault();
    event.stopPropagation();
    setFileDropActive(false);
    try {
      const raw = event.dataTransfer.getData(ITEM_DRAG_TYPE);
      const parsed = JSON.parse(raw) as { items?: Array<{ id: number; type: DriveItemType; folderId?: number | null }> };
      const targets = (parsed.items ?? [])
        .map((entry) => driveItems.find((candidate) => candidate.id === entry.id))
        .filter((candidate): candidate is DriveItem => candidate !== undefined);
      if (!targets.length) {
        setToast("Could not identify the dragged Drive items. Select them and try again.");
        return;
      }
      await moveItemsToFolder(targets, folder.folderId);
    } catch {
      setToast("Could not read the dragged items. Use Move to choose a destination instead.");
    }
  }

  function handleDragEnter(event: React.DragEvent<HTMLElement>) {
    const types = Array.from(event.dataTransfer.types);
    if (types.includes(ITEM_DRAG_TYPE)) {
      // Allow the drop target to receive an internal item without covering the UI.
      event.preventDefault();
      return;
    }
    if (!types.includes("Files")) return;

    event.preventDefault();
    const hasDirectory = Array.from(event.dataTransfer.items).some(
      (item) => getDroppedEntry(item)?.isDirectory,
    );
    setDragMessage(hasDirectory ? "Drop folder to prepare files" : "Drop files to upload");
    setFileDropActive(true);
  }

  function handleDragLeave(event: React.DragEvent<HTMLElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setFileDropActive(false);
  }

  function handleDragOver(event: React.DragEvent<HTMLElement>) {
    const types = Array.from(event.dataTransfer.types);
    if (types.includes(ITEM_DRAG_TYPE)) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      autoScrollDuringInternalDrag(event);
      return;
    }
    if (!types.includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setFileDropActive(true);
  }

  async function handleDrop(event: React.DragEvent<HTMLElement>) {
    const types = Array.from(event.dataTransfer.types);
    if (!types.includes(ITEM_DRAG_TYPE) && !types.includes("Files")) {
      event.preventDefault();
      setFileDropActive(false);
      setToast("This item type cannot be added to the upload queue.");
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setFileDropActive(false);
    if (types.includes(ITEM_DRAG_TYPE)) {
      setDropTargetFolderId(null);
      setToast("To move Drive items, drop them onto a folder or use Move to choose a destination.");
      return;
    }

    const entries = Array.from(event.dataTransfer.items)
      .filter((item) => item.kind === "file")
      .map(getDroppedEntry);
    const hasDirectory = entries.some((entry) => entry?.isDirectory);
    try {
      const readableEntries = entries.filter((entry): entry is DroppedEntry => entry !== null);
      const droppedFiles = readableEntries.length
        ? (await Promise.all(readableEntries.map(readDroppedEntry))).flat()
        : Array.from(event.dataTransfer.files).map((file) => ({ file, relativePath: file.name }));
      if (hasDirectory && droppedFiles.length === 0) {
        setToast("The browser didn't grant access to the dropped folder. Try Upload folder or select files instead.");
        return;
      }
      await addUploadFiles(droppedFiles);
    } catch (error) {
      setToast(error instanceof Error
        ? `${error.message} No files were added.`
        : "The browser couldn't read the dropped files. No files were added.");
    }
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

      {/* Keep both toolbars in the same fixed-height slot so switching between
          sorting controls and selection actions never moves the file list. */}
      <div className="relative mt-3 mb-2 h-10">
        <div
          role="toolbar"
          aria-label="Selected file actions"
          aria-hidden={selectedItems.length === 0}
          inert={selectedItems.length === 0}
          className={`absolute inset-0 flex h-full min-w-0 flex-nowrap items-center gap-1 overflow-x-auto rounded-xl border border-brand/15 bg-brand-soft/80 px-1.5 shadow-sm backdrop-blur-sm sm:gap-1.5 sm:px-2 transition-[opacity,transform,visibility] duration-200 ease-out motion-reduce:transition-none ${selectedItems.length > 0
            ? "visible translate-y-0 scale-100 opacity-100"
            : "invisible pointer-events-none -translate-y-1 scale-[0.985] opacity-0"
          }`}
        >
          <button
            type="button"
            aria-label="Clear selection"
            title="Clear selection"
            onClick={() => {
              setSelectedIds(new Set());
              setSelectionAnchorId(null);
            }}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
          >
            <X size={16} />
          </button>
          <span
            className="mr-1 inline-flex h-7 shrink-0 items-center border-r border-brand/15 px-2 pr-3 text-xs font-semibold tabular-nums text-brand-contrast"
            aria-live="polite"
          >
            {selectedItems.length} selected
          </span>
          {title === "Trash" && (
            <button
              type="button"
              aria-label="Restore selected items"
              title="Restore"
              onClick={() => void restoreItems(selectedItems)}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
            >
              <RotateCcw size={16} />
            </button>
          )}
          <button
            type="button"
            aria-label="Open"
            title="Open"
            onClick={() => runAction("Open", selectedItems[0])}
            disabled={selectedItems.length !== 1}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
          >
            <FolderOpen size={16} />
          </button>
          <button
            type="button"
            aria-label="Download"
            title="Download"
            onClick={() => runAction("Download")}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
          >
            <Download size={16} />
          </button>
          <button
            type="button"
            aria-label="Rename"
            title="Rename"
            onClick={() => runAction("Rename")}
            disabled={selectedItems.length !== 1 || !selectedCanManage}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
          >
            <Pencil size={16} />
          </button>
          {title !== "Shared with me" && title !== "Trash" && (
            <>
              <button
                type="button"
                aria-label={isMovingItems ? "Moving items" : "Move"}
                title={isMovingItems ? "Moving items…" : "Move"}
                onClick={() => runAction("Move")}
                disabled={isMovingItems || isDuplicatingItems || !selectedCanManage}
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
              >
                <Move size={16} />
              </button>
              <button
                type="button"
                aria-label={isDuplicatingItems ? "Duplicating items" : "Duplicate"}
                title={isDuplicatingItems ? "Duplicating items…" : "Duplicate"}
                onClick={() => runAction("Duplicate")}
                disabled={isDuplicatingItems || isMovingItems || !selectedCanManage}
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
              >
                <Copy size={16} />
              </button>
            </>
          )}
          {title !== "Trash" && (
            <button
              type="button"
              aria-label={selectedItems.every((item) => item.starred) ? "Remove from Starred" : "Add to Starred"}
              title={selectedItems.every((item) => item.starred) ? "Remove from Starred" : "Add to Starred"}
              onClick={() => void toggleStar(selectedItems)}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
            >
              <Star size={16} fill={selectedItems.every((item) => item.starred) ? "currentColor" : "none"} />
            </button>
          )}
          {title !== "Shared with me" && title !== "Trash" && selectedCanManage && (
            <button
              type="button"
              aria-label="Share"
              title="Share"
              onClick={() => runAction("Share")}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
            >
              <Share2 size={16} />
            </button>
          )}
          {(title === "Trash" || (title !== "Shared with me" && selectedCanManage)) && (
            <button
              type="button"
              aria-label={title === "Trash" ? "Delete permanently" : "Move to trash"}
              title={title === "Trash" ? "Delete permanently" : "Move to trash"}
              onClick={() => setPendingDestructive({
                action: title === "Trash" ? "delete" : "trash",
                count: selectedItems.length,
                targets: selectedItems,
              })}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-danger transition-colors hover:bg-danger/10 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-danger"
            >
              <Trash2 size={16} />
            </button>
          )}
        </div>

        <div
          aria-label="Sort and filter files"
          aria-hidden={selectedItems.length > 0}
          inert={selectedItems.length > 0}
          className={`absolute inset-0 flex h-full min-w-0 flex-nowrap items-center gap-2 overflow-x-auto px-2 transition-[opacity,transform,visibility] duration-200 ease-out motion-reduce:transition-none ${selectedItems.length === 0
            ? "visible translate-y-0 opacity-100"
            : "invisible pointer-events-none translate-y-1 opacity-0"
          }`}
        >
          <label className="sr-only" htmlFor="drive-sort">Sort files by</label>
          <div className="relative shrink-0">
            <select
              id="drive-sort"
              value={sortKey}
              onChange={(event) => setSortKey(event.target.value as SortKey)}
              className="h-8 appearance-none rounded-lg border border-border bg-surface py-1.5 pl-3 pr-8 text-xs text-foreground transition-colors hover:bg-background focus-visible:border-brand-contrast"
            >
              <option value="name">Name</option>
              <option value="modified">Last modified</option>
              <option value="size">File size</option>
              <option value="type">Type</option>
            </select>
            <ChevronDown size={15} aria-hidden="true" className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted" />
          </div>
          <button
            type="button"
            onClick={() => setSortDirection((current) => (current === "asc" ? "desc" : "asc"))}
            className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 text-xs text-foreground transition-colors duration-(--motion-fast) hover:bg-background"
            aria-label={`Sort ${sortKey} ${sortDirection === "asc" ? "descending" : "ascending"}`}
          >
            <ListFilter size={15} className="text-muted" />
            <span>{sortDirection === "asc" ? "Ascending" : "Descending"}</span>
            {sortDirection === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
          </button>
          <span className="ml-auto shrink-0 whitespace-nowrap text-xs font-medium text-muted" aria-live="polite">
            {listView ? `${driveItems.length} items` : title === "Starred" ? "No starred items yet" : "Demo UI · file actions not connected"}
          </span>
        </div>
      </div>
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
          <div className="min-w-0">
            <table className="w-full min-w-3xl border-separate border-spacing-0 text-left">
              <thead>
                <tr className="bg-background text-[13px] font-semibold text-muted">
                  <SortableHeading label="Name" field="name" current={sortKey} direction={sortDirection} onSort={(field) => { setSortKey(field); setSortDirection(sortKey === field && sortDirection === "asc" ? "desc" : "asc"); }} />
                  <th scope="col" className="sticky top-0 z-20 border-b border-border bg-background px-4 py-3">Owner</th>
                  <SortableHeading label="Date modified" field="modified" current={sortKey} direction={sortDirection} onSort={(field) => { setSortKey(field); setSortDirection(sortKey === field && sortDirection === "asc" ? "desc" : "asc"); }} />
                  <SortableHeading label="File size" field="size" current={sortKey} direction={sortDirection} onSort={(field) => { setSortKey(field); setSortDirection(sortKey === field && sortDirection === "asc" ? "desc" : "asc"); }} />
                  <th scope="col" className="sticky top-0 z-20 w-20 border-b border-border bg-background px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedItems.map((item) => (
                  <FileRow
                    key={item.id}
                    item={item}
                    selected={selectedIds.has(item.id)}
                    onToggle={(event) => handleItemClick(event, item.id)}
                    onOpen={() => openItem(item)}
                    onToggleStar={() => void toggleStar([item])}
                    showStar={title !== "Trash"}
                    actions={createActions(item)}
                    onDragStart={(event) => handleDragStart(event, item)}
                    onDragEnd={() => { setFileDropActive(false); setDropTargetFolderId(null); }}
                    onDragOverItem={(event) => handleFolderDragOver(event, item)}
                    onDropOnItem={(event) => void handleDropOnFolder(event, item)}
                    dropTarget={item.type === "folder" && item.folderId === dropTargetFolderId}
                  />
                ))}
              </tbody>
            </table>
            <div aria-hidden="true" className="h-12 select-none" />
          </div>
        ) : (
          <div className="space-y-5 p-3 sm:p-4">
            {folderItems.length > 0 && (
              <section aria-labelledby="drive-folders-heading" data-marquee-section="folders">
                <div data-no-marquee-selection="true" className="mb-2 flex items-center justify-between px-1">
                  <h3 id="drive-folders-heading" className="text-sm font-semibold text-foreground">Folders</h3>
                  <span className="text-xs text-muted">{folderItems.length}</span>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
                  {folderItems.map((item) => {
                    const selected = selectedIds.has(item.id);
                    return (
                      <article
                        key={item.id}
                        data-drive-item-id={item.id}
                        onClick={(event) => handleItemClick(event, item.id)}
                        onDoubleClick={() => openItem(item)}
                        onDragOver={(event) => handleFolderDragOver(event, item)}
                        onDrop={(event) => void handleDropOnFolder(event, item)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") openItem(item);
                          if (event.key === " ") { event.preventDefault(); toggleItem(item.id); }
                        }}
                        className={`flex h-14 min-w-0 items-center gap-2 rounded-xl border px-3 transition-colors duration-(--motion-fast) ${selected ? "border-brand-contrast bg-brand-soft ring-1 ring-brand-contrast/20" : "border-border bg-background hover:border-border-strong hover:bg-brand-soft/40"} ${dropTargetFolderId === item.folderId ? "ring-2 ring-brand-contrast bg-brand-soft" : ""}`}
                      >
                        <button
                          type="button"
                          draggable
                          data-no-marquee-selection="true"
                          onClick={(event) => event.stopPropagation()}
                          onPointerDown={(event) => event.stopPropagation()}
                          onDragStart={(event) => handleDragStart(event, item)}
                          onDragEnd={() => { setFileDropActive(false); setDropTargetFolderId(null); }}
                          aria-label={`Drag ${item.name}`}
                          title="Drag to move"
                          className="flex h-6 w-4 shrink-0 cursor-grab items-center justify-center text-muted active:cursor-grabbing"
                        >
                          <GripVertical size={14} />
                        </button>
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand-contrast">
                          {renderItemIcon("folder", 18)}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-left text-sm font-medium text-foreground" title={item.name}>
                          {item.name}
                        </span>
                        {title !== "Trash" && (
                          <button
                            type="button"
                            aria-label={item.starred ? `Remove ${item.name} from Starred` : `Add ${item.name} to Starred`}
                            title={item.starred ? "Remove from Starred" : "Add to Starred"}
                            onPointerDown={(event) => event.stopPropagation()}
                            onClick={(event) => { event.stopPropagation(); void toggleStar([item]); }}
                            className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-brand-soft ${item.starred ? "text-amber-500" : "text-muted opacity-60 hover:opacity-100"}`}
                          >
                            <Star size={15} fill={item.starred ? "currentColor" : "none"} />
                          </button>
                        )}
                        <span
                          onPointerDown={(event) => event.stopPropagation()}
                          onClick={(event) => event.stopPropagation()}
                          onDoubleClick={(event) => event.stopPropagation()}
                        >
                          <ContextMenu
                            label={`Actions for ${item.name}`}
                            trigger={<MoreHorizontal size={16} />}
                            actions={createActions(item)}
                          />
                        </span>
                      </article>
                    );
                  })}
                </div>
              </section>
            )}

            {fileItems.length > 0 && (
              <section aria-labelledby="drive-files-heading" data-marquee-section="files" className={folderItems.length > 0 ? "pt-1" : ""}>
                <div data-no-marquee-selection="true" className="mb-2 flex items-center justify-between px-1">
                  <h3 id="drive-files-heading" className="text-sm font-semibold text-foreground">Files</h3>
                  <span className="text-xs text-muted">{fileItems.length}</span>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
                  {fileItems.map((item) => {
                    const selected = selectedIds.has(item.id);
                    return (
                      <article
                        key={item.id}
                        data-drive-item-id={item.id}
                        onClick={(event) => handleItemClick(event, item.id)}
                        onDoubleClick={() => openItem(item)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") openItem(item);
                          if (event.key === " ") { event.preventDefault(); toggleItem(item.id); }
                        }}
                        className={`min-w-0 cursor-pointer rounded-xl border p-3 transition-colors duration-(--motion-fast) ${selected ? "border-brand-contrast bg-brand-soft/60 ring-1 ring-brand-contrast/20" : "border-border bg-surface hover:border-brand/30 hover:bg-brand-soft/25"}`}
                      >
                        <div className="flex min-w-0 items-center gap-1.5">
                          <button
                            type="button"
                            draggable
                            data-no-marquee-selection="true"
                            onClick={(event) => event.stopPropagation()}
                            onPointerDown={(event) => event.stopPropagation()}
                            onDragStart={(event) => handleDragStart(event, item)}
                            onDragEnd={() => { setFileDropActive(false); setDropTargetFolderId(null); }}
                            aria-label={`Drag ${item.name}`}
                            title="Drag to move"
                            className="flex h-6 w-5 shrink-0 cursor-grab items-center justify-center text-muted active:cursor-grabbing"
                          >
                            <GripVertical size={14} />
                          </button>
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand-contrast">
                            {renderItemIcon(item.type, 16)}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-left text-sm font-medium text-foreground" title={item.name}>
                            {item.name}
                          </span>
                          {title !== "Trash" && (
                            <button
                              type="button"
                              aria-label={item.starred ? `Remove ${item.name} from Starred` : `Add ${item.name} to Starred`}
                              title={item.starred ? "Remove from Starred" : "Add to Starred"}
                              onPointerDown={(event) => event.stopPropagation()}
                              onClick={(event) => { event.stopPropagation(); void toggleStar([item]); }}
                              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-brand-soft ${item.starred ? "text-amber-500" : "text-muted opacity-60 hover:opacity-100"}`}
                            >
                              <Star size={15} fill={item.starred ? "currentColor" : "none"} />
                            </button>
                          )}
                          <span
                            onPointerDown={(event) => event.stopPropagation()}
                            onClick={(event) => event.stopPropagation()}
                            onDoubleClick={(event) => event.stopPropagation()}
                          >
                            <ContextMenu
                              label={`Actions for ${item.name}`}
                              trigger={<MoreHorizontal size={16} />}
                              actions={createActions(item)}
                            />
                          </span>
                        </div>
                        <div className="mt-3 flex items-center justify-between gap-2 pl-13 text-xs text-muted">
                          <span className="min-w-0 truncate" title="Date modified">{item.modified}</span>
                          <span className="shrink-0">{item.size}</span>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </section>
            )}

          </div>
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

      {isCreateFolderOpen && (
        <div
          className="fixed inset-0 z-100 flex items-center justify-center bg-black/30 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !isCreatingFolder) {
              setIsCreateFolderOpen(false);
            }
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-folder-title"
            className="w-full max-w-126.5 rounded-4xl bg-background px-7.5 pb-7 pt-7.5 shadow-xl"
          >
            <h2
              id="create-folder-title"
              className="mb-6 text-[28px] font-normal tracking-tight text-foreground"
            >
              New folder
            </h2>

            <form
              onSubmit={(event) => {
                event.preventDefault();
                void handleCreateFolder();
              }}
            >
              <input
                autoFocus
                autoComplete="off"
                maxLength={255}
                value={newFolderName}
                onFocus={(event) => event.currentTarget.select()}
                onChange={(event) => {
                  setNewFolderName(event.target.value);
                  setFolderNameError("");
                }}
                placeholder="Untitled folder"
                aria-label="Folder name"
                aria-invalid={Boolean(folderNameError)}
                disabled={isCreatingFolder}
                className="h-17.5 w-full rounded-[5px] border-2 border-brand bg-transparent px-4.5 text-[20px] text-foreground outline-none focus:ring-0"
              />

              {folderNameError && (
                <p className="mt-2 text-sm text-red-600" role="alert">
                  {folderNameError}
                </p>
              )}

              <div className="mt-7 flex justify-end gap-2">
                <button
                  type="button"
                  disabled={isCreatingFolder}
                  onClick={() => setIsCreateFolderOpen(false)}
                  className="min-w-20.5 rounded-lg px-4 py-2.5 text-base font-medium text-brand-contrast hover:bg-brand-soft disabled:opacity-50"
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  disabled={isCreatingFolder || !newFolderName.trim()}
                  className="min-w-20.5 rounded-lg px-4 py-2.5 text-base font-medium text-brand-contrast hover:bg-brand-soft disabled:opacity-50"
                >
                  {isCreatingFolder ? "Creating..." : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {isMoveDialogOpen && (
        <div
          className="fixed inset-0 z-100 flex items-center justify-center bg-black/35 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !isMovingItems) setIsMoveDialogOpen(false);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="move-items-title"
            className="flex max-h-[min(80vh,680px)] w-full max-w-155 flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl"
          >
            <header className="border-b border-border px-5 py-4">
              <h2 id="move-items-title" className="text-lg font-semibold text-foreground">Move {moveTargets.length} item{moveTargets.length === 1 ? "" : "s"}</h2>
              <p className="mt-1 text-sm text-muted">Choose a destination folder. You can also drag items onto a folder in Drive.</p>
            </header>
            <div className="flex flex-wrap items-center gap-1 border-b border-border px-5 py-3 text-sm">
              <button type="button" onClick={() => void loadMoveDestination(null)} className="rounded-md px-2 py-1 font-medium text-brand-contrast hover:bg-brand-soft">My Drive</button>
              {(moveDestinationDetails?.ancestors ?? []).map((ancestor) => (
                <span key={ancestor.id} className="inline-flex items-center gap-1">
                  <span className="text-muted">/</span>
                  <button type="button" onClick={() => void loadMoveDestination(ancestor.id)} className="rounded-md px-2 py-1 text-brand-contrast hover:bg-brand-soft">{ancestor.name}</button>
                </span>
              ))}
              {moveDestinationDetails && <span className="inline-flex items-center gap-1"><span className="text-muted">/</span><span className="rounded-md bg-brand-soft px-2 py-1 font-semibold text-brand-contrast">{moveDestinationDetails.name}</span></span>}
            </div>
            <div className="min-h-55 flex-1 overflow-y-auto p-3">
              {moveDestinationLoading ? (
                <div className="flex min-h-40 items-center justify-center text-sm text-muted">Loading folders…</div>
              ) : moveDestinationError ? (
                <div className="rounded-lg border border-danger/30 bg-background p-4 text-sm text-danger" role="alert">
                  <p>{moveDestinationError}</p>
                  <button type="button" onClick={() => void loadMoveDestination(moveDestinationId)} className="mt-2 font-semibold underline">Try again</button>
                </div>
              ) : moveDestinationItems.length === 0 ? (
                <div className="flex min-h-40 flex-col items-center justify-center text-center">
                  <FolderOpen size={28} className="mb-2 text-muted" />
                  <p className="text-sm font-medium text-foreground">No subfolders here</p>
                  <p className="mt-1 text-xs text-muted">Move here will place the selected items in this location.</p>
                </div>
              ) : (
                <ul className="space-y-1">
                  {moveDestinationItems.map((folder) => (
                    <li key={folder.id} className="flex items-center gap-2 rounded-lg border border-transparent px-2 py-1.5 hover:border-border hover:bg-background">
                      <Folder size={17} className="shrink-0 text-brand-contrast" />
                      <button type="button" onClick={() => folder.folderId && void loadMoveDestination(folder.folderId)} className="min-w-0 flex-1 truncate py-1 text-left text-sm text-foreground" title={`Open ${folder.name}`}>{folder.name}</button>
                      <button type="button" disabled={!folder.folderId || moveDestinationLoading} onClick={() => folder.folderId && void loadMoveDestination(folder.folderId)} className="rounded-md px-2 py-1 text-xs font-medium text-brand-contrast hover:bg-brand-soft disabled:opacity-50">Open</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <footer className="flex items-center justify-between gap-3 border-t border-border bg-background px-5 py-4">
              <p className="min-w-0 truncate text-xs text-muted">Destination: {moveDestinationDetails ? moveDestinationDetails.location || moveDestinationDetails.name : "My Drive (root)"}</p>
              <div className="flex shrink-0 items-center gap-2">
                <Button variant="ghost" onClick={() => setIsMoveDialogOpen(false)} disabled={isMovingItems}>Cancel</Button>
                <Button onClick={() => void confirmMoveItems()} disabled={isMovingItems || moveDestinationLoading || Boolean(moveDestinationError)}>
                  {isMovingItems ? "Moving…" : "Move here"}
                </Button>
              </div>
            </footer>
          </section>
        </div>
      )}

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

      {shareDialogOpen && (
        <div className="fixed inset-0 z-100 flex items-center justify-center bg-black/40 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !sharing) setShareDialogOpen(false); }}>
          <form onSubmit={(event) => void submitShare(event)} aria-labelledby="share-items-title" className="w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-surface shadow-xl">
            <header className="border-b border-border px-5 py-4">
              <h2 id="share-items-title" className="text-lg font-semibold text-foreground">Share {shareTargets.length} item{shareTargets.length === 1 ? "" : "s"}</h2>
              <p className="mt-1 text-sm text-muted">Grant access to an existing SecureDrive account by email.</p>
            </header>
            <div className="space-y-4 px-5 py-5">
              <label className="block text-sm font-medium text-foreground">
                Email address
                <input
                  type="email"
                  required
                  autoFocus
                  value={shareEmail}
                  onChange={(event) => setShareEmail(event.target.value)}
                  placeholder="name@example.com"
                  autoComplete="email"
                  className="mt-1.5 h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none focus:border-brand-contrast focus:ring-2 focus:ring-brand-soft"
                />
              </label>
              <label className="block text-sm font-medium text-foreground">
                Access level
                <select value={sharePermission} onChange={(event) => setSharePermission(event.target.value as "viewer" | "editor")} className="mt-1.5 h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none focus:border-brand-contrast focus:ring-2 focus:ring-brand-soft">
                  <option value="viewer">Viewer — can view and download</option>
                  <option value="editor">Editor — can modify shared items</option>
                </select>
              </label>
              <p className="text-xs leading-5 text-muted">The recipient must already have an active SecureDrive account registered with this email. SecureDrive will attempt to send a notification if outgoing email is configured; access permissions are applied independently.</p>
            </div>
            <footer className="flex justify-end gap-2 border-t border-border bg-background px-5 py-4">
              <Button variant="ghost" onClick={() => setShareDialogOpen(false)} disabled={sharing}>Cancel</Button>
              <Button type="submit" disabled={sharing || !shareEmail.trim()}>{sharing ? "Sharing…" : "Share"}</Button>
            </footer>
          </form>
        </div>
      )}

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

function SortableHeading({
  label,
  field,
  current,
  direction,
  onSort,
}: {
  label: string;
  field: SortKey;
  current: SortKey;
  direction: SortDirection;
  onSort: (field: SortKey) => void;
}) {
  const active = current === field;
  return (
    <th scope="col" aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"} className="sticky top-0 z-20 border-b border-border bg-background px-4 py-2">
      <button
        type="button"
        onClick={() => onSort(field)}
        className="inline-flex min-h-9 items-center gap-2 rounded-lg text-left transition-colors duration-(--motion-fast) hover:text-brand-contrast"
      >
        {label}
        {active && (direction === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />)}
      </button>
    </th>
  );
}

function FileRow({
  item,
  selected,
  onToggle,
  onOpen,
  onToggleStar,
  showStar,
  actions,
  onDragStart,
  onDragEnd,
  onDragOverItem,
  onDropOnItem,
  dropTarget,
}: {
  item: DriveItem;
  selected: boolean;
  onToggle: (event: React.MouseEvent<HTMLTableRowElement>) => void;
  onOpen: () => void;
  onToggleStar: () => void;
  showStar: boolean;
  actions: ContextMenuAction[];
  onDragStart: (event: React.DragEvent<HTMLButtonElement>) => void;
  onDragEnd: () => void;
  onDragOverItem: (event: React.DragEvent<HTMLTableRowElement>) => void;
  onDropOnItem: (event: React.DragEvent<HTMLTableRowElement>) => void;
  dropTarget: boolean;
}) {
  return (
    <tr
      data-drive-item-id={item.id}
      aria-selected={selected}
      onClick={onToggle}
      onDoubleClick={() => onOpen()}
      onDragOver={onDragOverItem}
      onDrop={onDropOnItem}
      className={`cursor-pointer transition-colors duration-(--motion-fast) ${selected ? "bg-brand-soft/60" : "hover:bg-brand-soft/25"} ${dropTarget ? "bg-brand-soft ring-2 ring-inset ring-brand-contrast" : ""}`}
    >
      <th scope="row" className="max-w-[24rem] border-b border-border px-3 py-2 text-left font-normal">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            draggable
            onClick={(event) => event.stopPropagation()}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            aria-label={`Drag ${item.name}`}
            data-no-marquee-selection="true"
            onPointerDown={(event) => event.stopPropagation()}
            title="Drag to move"
            className="flex h-9 w-7 shrink-0 cursor-grab items-center justify-center rounded-lg text-muted transition-colors hover:bg-brand-soft hover:text-brand-contrast active:cursor-grabbing focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
          >
            <GripVertical size={16} />
          </button>
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-brand-soft text-brand-contrast">
            {renderItemIcon(item.type, 19)}
          </span>
          <span className="min-w-0 truncate rounded text-left text-sm text-foreground" title={item.name}>
            {item.name}
          </span>
          {showStar && (
            <button
              type="button"
              aria-label={item.starred ? `Remove ${item.name} from Starred` : `Add ${item.name} to Starred`}
              title={item.starred ? "Remove from Starred" : "Add to Starred"}
              data-no-marquee-selection="true"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => { event.stopPropagation(); onToggleStar(); }}
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-brand-soft ${item.starred ? "text-amber-500" : "text-muted opacity-60 hover:opacity-100"}`}
            >
              <Star size={15} fill={item.starred ? "currentColor" : "none"} />
            </button>
          )}
        </div>
      </th>
      <td className="border-b border-border px-4 py-2">
        <span className="inline-flex min-h-10 items-center gap-2 text-sm text-foreground">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[10px] font-semibold text-brand-contrast">
            {item.ownerInitials}
          </span>
          <span className="truncate text-sm">{item.owner}</span>
        </span>
      </td>
      <td className="whitespace-nowrap border-b border-border px-4 py-2 text-sm text-foreground">{item.modified}</td>
      <td className="whitespace-nowrap border-b border-border px-4 py-2 text-sm text-foreground">{item.size}</td>
      <td className="border-b border-border px-3 py-2 text-right" onClick={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()}>
        <ContextMenu
          label={`Actions for ${item.name}`}
          trigger={<MoreHorizontal size={18} />}
          actions={actions}
        />
      </td>
    </tr>
  );
}
