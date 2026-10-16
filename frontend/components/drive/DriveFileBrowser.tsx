"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
  Trash2,
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

type ViewMode = "list" | "grid";
type SortDirection = "asc" | "desc";
type SortKey = "name" | "modified" | "size" | "type";
type DriveItemType = "folder" | "document" | "image";
type PendingDestructiveAction = {
  action: "trash" | "delete";
  count: number;
};

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
  return <DriveFileBrowserContent key={title} title={title} items={items} />;
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
  const [dragActive, setDragActive] = useState(false);
  const [dragMessage, setDragMessage] = useState("Drop files to upload");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const loadRequestIdRef = useRef(0);
  const { enqueue, openManager } = useUploadManager();

  const loadItems = useCallback(async (folderId: number | null, view: DriveListView) => {
    const requestId = ++loadRequestIdRef.current;
    setLoading(true);
    setLoadError(null);
    try {
      if (view === "drive" && folderId !== null) {
        setFolderDetails(null);
        const [details, nextItems] = await Promise.all([
          getDriveFolderDetails(folderId),
          getDriveItems(folderId, view),
        ]);
        if (requestId !== loadRequestIdRef.current) return;
        setFolderDetails(details);
        setDriveItems(nextItems);
      } else {
        const nextItems = await getDriveItems(folderId, view);
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

  useEffect(() => {
    if (!listView) return;
    const timer = window.setTimeout(() => {
      void loadItems(listView === "drive" ? currentFolderId : null, listView);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [listView, currentFolderId, loadItems]);

  useEffect(() => {
    function handleUploadCompleted(event: Event) {
      const detail = (event as CustomEvent<{ destinationId: string | null }>).detail;
      if (!detail || !listView) return;

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

  useEffect(() => {
    setSelectedIds(new Set());
  }, [currentFolderId]);

  const selectedItems = useMemo(
    () => driveItems.filter((item) => selectedIds.has(item.id)),
    [driveItems, selectedIds],
  );
  const sortedItems = useMemo(
    () =>
      [...driveItems].sort((first, second) => {
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
  const allSelected = sortedItems.length > 0 && sortedItems.every((item) => selectedIds.has(item.id));
  const someSelected = !allSelected && sortedItems.some((item) => selectedIds.has(item.id));

  function addUploadFiles(files: readonly { file: File; relativePath: string }[]) {
    if (files.length === 0) {
      setToast("No files were provided by the browser. Folder access may have been denied.");
      return;
    }
    if (files.length > MAX_UPLOAD_FILES_PER_BATCH) {
      setToast(`A batch can contain at most ${MAX_UPLOAD_FILES_PER_BATCH} files. None of this selection was added.`);
      return;
    }

    enqueue(files.map(({ file, relativePath }) => {
      const normalizedPath = relativePath.replace(/\\/g, "/");
      const validationError = validateUploadPath(normalizedPath, file);
      return {
        file,
        relativePath: normalizedPath,
        validationError,
      };
    }), currentFolderId !== null ? String(currentFolderId) : null);
    openManager();
  }

  function handleSelectedFiles(fileList: FileList | null) {
    if (!fileList) return;
    const selected = Array.from(fileList).map((file) => ({
      file,
      relativePath: file.webkitRelativePath || file.name,
    }));
    addUploadFiles(selected);
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
      const result = await requestAccountApi<{
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
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (
        event.target instanceof Element
        && event.target.closest('[role="menu"], dialog[open]')
      ) return;
      setSelectedIds(new Set());
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  function toggleItem(id: number) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelectedIds((current) => {
      if (sortedItems.length && sortedItems.every((item) => current.has(item.id))) {
        return new Set();
      }
      return new Set(sortedItems.map((item) => item.id));
    });
  }

  function showNotConnected(action: string) {
    setToast(`${action} isn't connected yet. No files were changed.`);
  }

  function openItem(item: DriveItem) {
    if (item.type !== "folder") {
      showNotConnected("Opening files");
      return;
    }
    if (listView !== "drive") {
      showNotConnected("Opening folders from this view");
      return;
    }
    if (!Number.isSafeInteger(item.folderId) || !item.folderId || item.folderId <= 0) {
      setToast("This folder has an invalid ID and cannot be opened.");
      return;
    }
    setSelectedIds(new Set());
    router.push(`/drive/folders/${item.folderId}`);
  }

  function runAction(action: string, item?: DriveItem) {
    if (action === "Open" && item) {
      openItem(item);
    } else if (action === "Download") {
      const targets = item ? [item] : selectedItems;
      void downloadItems(targets);
    } else if (action === "Move to trash" || action === "Delete permanently") {
      setPendingDestructive({
        action: action === "Move to trash" ? "trash" : "delete",
        count: item ? 1 : selectedItems.length,
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
    const actions: ContextMenuAction[] = [];

    if (actionTarget.length === 1) {
      actions.push({
        label: "Open",
        onSelect: () => runAction("Open", actionTarget[0]),
      });
    }
    actions.push(
      { label: "Download", onSelect: () => runAction("Download", item) },
      { label: "Rename", onSelect: () => runAction("Rename", item), disabled: actionTarget.length !== 1 },
      { label: "Move", onSelect: () => runAction("Move", item) },
      { label: "Copy", onSelect: () => runAction("Copy", item) },
    );
    if (title !== "Shared with me" && title !== "Trash") {
      actions.push({ label: "Share", onSelect: () => runAction("Share", item) });
    }
    if (title === "Trash") {
      actions.push({
        label: "Delete permanently",
        onSelect: () => runAction("Delete permanently", item),
        destructive: true,
      });
    } else {
      actions.push({
        label: onlySelectedFolder ? "Move folder to trash" : "Move to trash",
        onSelect: () => runAction("Move to trash", item),
        destructive: true,
      });
    }
    return actions;
  }

  function handleDragStart(event: React.DragEvent<HTMLButtonElement>, item: DriveItem) {
    event.dataTransfer.setData(ITEM_DRAG_TYPE, String(item.id));
    event.dataTransfer.effectAllowed = "move";
    setDragMessage("Drop Drive item to move · not connected");
    setDragActive(true);
  }

  function handleDragEnter(event: React.DragEvent<HTMLElement>) {
    const types = Array.from(event.dataTransfer.types);
    if (!types.includes(ITEM_DRAG_TYPE) && !types.includes("Files")) return;
    event.preventDefault();
    const hasDirectory = Array.from(event.dataTransfer.items).some(
      (item) => getDroppedEntry(item)?.isDirectory,
    );
    setDragMessage(
      types.includes(ITEM_DRAG_TYPE)
        ? "Drop Drive item to move · not connected"
        : hasDirectory
          ? "Drop folder to prepare files"
          : "Drop files to upload",
    );
    setDragActive(true);
  }

  function handleDragLeave(event: React.DragEvent<HTMLElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setDragActive(false);
  }

  function handleDragOver(event: React.DragEvent<HTMLElement>) {
    const types = Array.from(event.dataTransfer.types);
    if (!types.includes(ITEM_DRAG_TYPE) && !types.includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = types.includes(ITEM_DRAG_TYPE) ? "move" : "copy";
  }

  async function handleDrop(event: React.DragEvent<HTMLElement>) {
    const types = Array.from(event.dataTransfer.types);
    if (!types.includes(ITEM_DRAG_TYPE) && !types.includes("Files")) {
      event.preventDefault();
      setDragActive(false);
      setToast("This item type cannot be added to the upload queue.");
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);
    if (types.includes(ITEM_DRAG_TYPE)) {
      setToast("This drop is for a Drive item, not a local upload. Moving files isn't connected.");
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
      addUploadFiles(droppedFiles);
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

  return (
    <section
      className={`relative m-2 min-h-[calc(100%-16px)] bg-background p-0 sm:m-3 ${dragActive ? "ring-2 ring-inset ring-brand-contrast" : ""}`}
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
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 px-1 pt-1 sm:px-2 sm:pt-2">
        <Breadcrumb items={folderPath} className="min-w-0 [&>ol]:text-lg [&>ol]:font-semibold sm:[&>ol]:text-xl" />

        <div className="flex shrink-0 items-center gap-1.5">
          <DriveNewMenu />
          <div className="flex items-center gap-0.5 rounded-xl border border-border bg-background p-0.5">
            <button
              type="button"
              onClick={() => setView("list")}
              className={`flex h-9 w-9 items-center justify-center rounded-[9px] border border-transparent transition-colors duration-[var(--motion-fast)] ${view === "list" ? "bg-brand-soft text-brand-contrast" : "text-muted hover:bg-surface hover:text-foreground"}`}
              aria-label="List view"
              aria-pressed={view === "list"}
            >
              <List size={16} />
            </button>
            <button
              type="button"
              onClick={() => setView("grid")}
              className={`flex h-9 w-9 items-center justify-center rounded-[9px] border border-transparent transition-colors duration-[var(--motion-fast)] ${view === "grid" ? "bg-brand-soft text-brand-contrast" : "text-muted hover:bg-surface hover:text-foreground"}`}
              aria-label="Grid view"
              aria-pressed={view === "grid"}
            >
              <Grid2x2 size={16} />
            </button>
          </div>
        </div>
      </div>

      {selectedItems.length > 0 ? (
        <div
          role="toolbar"
          aria-label="Selected file actions"
          className="mt-3 mb-2 flex h-10 min-h-10 flex-nowrap items-center gap-1 overflow-x-auto rounded-lg border border-brand/20 bg-brand-soft px-2 py-1 sm:gap-1.5 sm:px-2.5 [&>button]:h-8 [&>button]:shrink-0 [&>span]:shrink-0"
        >
          <span className="shrink-0 px-1 text-xs font-semibold text-brand-contrast">
            {selectedItems.length} selected
          </span>
          <Button size="sm" variant="ghost" onClick={() => runAction("Open", selectedItems[0])} disabled={selectedItems.length !== 1}>
            <FolderOpen size={15} /> Open
          </Button>
          <Button size="sm" variant="ghost" onClick={() => runAction("Download")}>
            <Download size={15} /> Download
          </Button>
          <Button size="sm" variant="ghost" onClick={() => runAction("Rename")} disabled={selectedItems.length !== 1}>
            <Pencil size={15} /> Rename
          </Button>
          <Button size="sm" variant="ghost" onClick={() => runAction("Move")}>
            <Move size={15} /> Move
          </Button>
          <Button size="sm" variant="ghost" onClick={() => runAction("Copy")}>
            <Copy size={15} /> Copy
          </Button>
          {title !== "Shared with me" && title !== "Trash" && (
            <Button size="sm" variant="ghost" onClick={() => runAction("Share")}>
              <Share2 size={15} /> Share
            </Button>
          )}
          <Button
            size="sm"
            variant="destructive"
            onClick={() => setPendingDestructive({
              action: title === "Trash" ? "delete" : "trash",
              count: selectedItems.length,
            })}
          >
            <Trash2 size={15} /> {title === "Trash" ? "Delete permanently" : "Move to trash"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            onClick={() => setSelectedIds(new Set())}
          >
            <X size={15} /> Clear selection
          </Button>
        </div>
      ) : (
        <div className="mt-3 mb-2 flex h-10 flex-wrap items-center gap-2 px-1 sm:gap-2 sm:px-2">
          <label className="sr-only" htmlFor="drive-sort">Sort files by</label>
          <div className="relative">
            <select
              id="drive-sort"
              value={sortKey}
              onChange={(event) => setSortKey(event.target.value as SortKey)}
              className="h-8 appearance-none rounded-lg border border-border bg-surface py-1.5 pl-3 pr-8 text-xs text-foreground hover:bg-background"
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
            className="flex h-8 items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 text-xs text-foreground transition-colors duration-[var(--motion-fast)] hover:bg-background"
            aria-label={`Sort ${sortKey} ${sortDirection === "asc" ? "descending" : "ascending"}`}
          >
            <ListFilter size={15} className="text-muted" />
            <span>{sortDirection === "asc" ? "Ascending" : "Descending"}</span>
            {sortDirection === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
          </button>
          <span className="ml-auto text-xs font-medium text-muted">
            {listView ? `${driveItems.length} items` : title === "Starred" ? "Starred items are not available" : "Demo UI · file actions not connected"}
          </span>
        </div>
      )}

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

      <div
        className={`relative rounded-xl border-t bg-surface transition-colors duration-[var(--motion-fast)] ${dragActive ? "border-brand-contrast ring-2 ring-brand-contrast/30" : "border-border"
          }`}
      >
        {loading ? (
          <EmptyState title={`Loading ${title}`} description="Fetching items from your account…" />
        ) : loadError ? (
          <EmptyState title="Could not load your Drive" description={loadError} action={
            <Button variant="secondary" size="sm" onClick={() => listView && void loadItems(listView === "drive" ? currentFolderId : null, listView)}>Try again</Button>
          } />
        ) : sortedItems.length === 0 ? (
          <EmptyState
            title={title === "Starred" ? "Starred items are not available" : title === "Trash" ? "Trash is empty" : title === "Recent" ? "No recent files" : "No files here"}
            description={
              title === "Starred"
                ? "SecureDrive does not yet support starring files."
                : listView
                  ? title === "Recent"
                    ? "Files you open will appear here."
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
          <div className="overflow-x-auto">
            <table className="w-full min-w-[780px] border-collapse text-left">
              <thead>
                <tr className="border-b border-border bg-background text-xs font-semibold text-muted">
                  <th scope="col" className="w-12 px-3 py-3">
                    <input
                      type="checkbox"
                      aria-label="Select all items"
                      checked={allSelected}
                      ref={(element) => {
                        if (element) element.indeterminate = someSelected;
                      }}
                      onChange={toggleAll}
                      className="h-4 w-4 accent-brand-contrast"
                    />
                  </th>
                  <SortableHeading label="Name" field="name" current={sortKey} direction={sortDirection} onSort={(field) => { setSortKey(field); setSortDirection(sortKey === field && sortDirection === "asc" ? "desc" : "asc"); }} />
                  <th scope="col" className="px-4 py-3">Owner</th>
                  <SortableHeading label="Date modified" field="modified" current={sortKey} direction={sortDirection} onSort={(field) => { setSortKey(field); setSortDirection(sortKey === field && sortDirection === "asc" ? "desc" : "asc"); }} />
                  <SortableHeading label="File size" field="size" current={sortKey} direction={sortDirection} onSort={(field) => { setSortKey(field); setSortDirection(sortKey === field && sortDirection === "asc" ? "desc" : "asc"); }} />
                  <th scope="col" className="w-20 px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedItems.map((item) => (
                  <FileRow
                    key={item.id}
                    item={item}
                    selected={selectedIds.has(item.id)}
                    onToggle={() => toggleItem(item.id)}
                    onOpen={() => openItem(item)}
                    actions={createActions(item)}
                    onDragStart={(event) => handleDragStart(event, item)}
                    onDragEnd={() => setDragActive(false)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-2 p-2 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
            {sortedItems.map((item) => {
              const selected = selectedIds.has(item.id);
              return (
                <article
                  key={item.id}
                  className={`min-w-0 rounded-2xl border p-4 transition-colors duration-[var(--motion-fast)] ${selected ? "border-brand-contrast bg-brand-soft/60" : "border-border bg-surface hover:bg-background"
                    }`}
                >
                  <div className="flex min-w-0 items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={selected}
                      aria-label={`Select ${item.name}`}
                      onChange={() => toggleItem(item.id)}
                      className="h-3.5 w-3.5 shrink-0 accent-brand-contrast"
                    />
                    <button
                      type="button"
                      draggable
                      onDragStart={(event) => handleDragStart(event, item)}
                      onDragEnd={() => setDragActive(false)}
                      aria-label={`Drag ${item.name}`}
                      title="Drag to move"
                      className="flex h-6 w-5 shrink-0 cursor-grab items-center justify-center text-muted active:cursor-grabbing"
                    >
                      <GripVertical size={14} />
                    </button>
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand-contrast">
                      {renderItemIcon(item.type, 16)}
                    </span>
                    <button
                      type="button"
                      onClick={() => openItem(item)}
                      className="min-w-0 flex-1 truncate text-left text-xs font-medium text-foreground"
                      title={item.name}
                    >
                      {item.name}
                    </button>
                    <ContextMenu
                      label={`Actions for ${item.name}`}
                      trigger={<MoreHorizontal size={16} />}
                      actions={createActions(item)}
                    />
                  </div>
                  {item.type !== "folder" && (
                    <div className="mt-2 flex items-center justify-between gap-2 pl-[3.25rem] text-[11px] text-muted">
                      <span className="min-w-0 truncate" title="Date modified (upload date is not currently provided by the item model)">
                        {item.modified}
                      </span>
                      <span className="shrink-0">{item.size}</span>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </div>

      {isCreateFolderOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/30 p-4"
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
            className="w-full max-w-[506px] rounded-[32px] bg-background px-[30px] pb-[28px] pt-[30px] shadow-xl"
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
                className="h-[70px] w-full rounded-[5px] border-2 border-brand bg-transparent px-[18px] text-[20px] text-foreground outline-none focus:ring-0"
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
                  className="min-w-[82px] rounded-lg px-4 py-2.5 text-base font-medium text-brand-contrast hover:bg-brand-soft disabled:opacity-50"
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  disabled={isCreatingFolder || !newFolderName.trim()}
                  className="min-w-[82px] rounded-lg px-4 py-2.5 text-base font-medium text-brand-contrast hover:bg-brand-soft disabled:opacity-50"
                >
                  {isCreatingFolder ? "Creating..." : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {toast && (
        <div className="fixed bottom-4 right-4 z-[80] w-[min(24rem,calc(100vw-2rem))]">
          <Toast title={toastTitle} variant={toastVariant} onDismiss={() => setToast(null)}>
            {toast}
          </Toast>
        </div>
      )}

      {dragActive && (
        <div
          aria-live="polite"
          className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center rounded-xl bg-brand-soft/90 p-4 text-center text-base font-semibold text-brand-contrast"
        >
          {dragMessage}
        </div>
      )}

      <ConfirmDialog
        open={pendingDestructive !== null}
        title={pendingDestructive?.action === "delete" ? "Delete permanently?" : "Move to trash?"}
        description={
          pendingDestructive?.action === "delete"
            ? `This would permanently delete ${pendingDestructive.count} item(s). This action is not connected, so no files will be deleted.`
            : `This would move ${pendingDestructive?.count ?? 1} item(s) to Trash. This action is not connected, so no files will be moved.`
        }
        confirmLabel={pendingDestructive?.action === "delete" ? "Delete permanently" : "Move to trash"}
        destructive
        onClose={() => setPendingDestructive(null)}
        onConfirm={() => {
          const action = pendingDestructive?.action;
          setPendingDestructive(null);
          showNotConnected(action === "delete" ? "Permanent deletion" : "Moving to trash");
        }}
      />
    </section>
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
    <th scope="col" aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"} className="px-4 py-2">
      <button
        type="button"
        onClick={() => onSort(field)}
        className="inline-flex min-h-9 items-center gap-2 rounded-lg text-left transition-colors duration-[var(--motion-fast)] hover:text-brand-contrast"
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
  actions,
  onDragStart,
  onDragEnd,
}: {
  item: DriveItem;
  selected: boolean;
  onToggle: () => void;
  onOpen: () => void;
  actions: ContextMenuAction[];
  onDragStart: (event: React.DragEvent<HTMLButtonElement>) => void;
  onDragEnd: () => void;
}) {
  return (
    <tr
      aria-selected={selected}
      className={`border-b border-border transition-colors duration-[var(--motion-fast)] last:border-b-0 ${selected ? "bg-brand-soft/60" : "hover:bg-background"
        }`}
    >
      <td className="w-12 px-3 py-2">
        <input
          type="checkbox"
          checked={selected}
          aria-label={`Select ${item.name}`}
          onChange={onToggle}
          className="h-4 w-4 accent-brand-contrast"
        />
      </td>
      <th scope="row" className="max-w-[24rem] px-3 py-2 text-left font-normal">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            draggable
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            aria-label={`Drag ${item.name}`}
            title="Drag to move"
            className="flex h-9 w-7 shrink-0 cursor-grab items-center justify-center rounded-lg text-muted active:cursor-grabbing"
          >
            <GripVertical size={16} />
          </button>
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-brand-soft text-brand-contrast">
            {renderItemIcon(item.type, 19)}
          </span>
          <button type="button" onClick={onOpen} className="min-w-0 truncate rounded text-left text-sm text-foreground">
            {item.name}
          </button>
        </div>
      </th>
      <td className="px-4 py-2">
        <span className="inline-flex min-h-10 items-center gap-2 text-sm text-foreground">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[10px] font-semibold text-brand-contrast">
            {item.ownerInitials}
          </span>
          <span className="truncate">{item.owner}</span>
        </span>
      </td>
      <td className="whitespace-nowrap px-4 py-2 text-sm text-foreground">{item.modified}</td>
      <td className="whitespace-nowrap px-4 py-2 text-sm text-foreground">{item.size}</td>
      <td className="px-3 py-2 text-right">
        <ContextMenu
          label={`Actions for ${item.name}`}
          trigger={<MoreHorizontal size={18} />}
          actions={actions}
        />
      </td>
    </tr>
  );
}
