"use client";

import { useCallback, useEffect, useRef, useState, type Dispatch, type DragEvent, type SetStateAction } from "react";
import { DRIVE_UPLOAD_FILES_EVENT, DRIVE_UPLOAD_FOLDER_EVENT } from "@/components/drive/DriveNewMenu";
import { DRIVE_UPLOAD_COMPLETED_EVENT, useUploadManager } from "@/components/drive/UploadManager";
import { getDriveItems, type DriveListView } from "@/lib/drive-service";
import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import { FOLDER_TREE_REFRESH_EVENT } from "@/lib/workspace-context";
import { ITEM_DRAG_TYPE } from "./drive-move-utils";
import {
  MAX_UPLOAD_FILES_PER_BATCH, getDroppedEntry, readDroppedEntry,
  validateUploadPath, getDriveDropKind, preferClipboardFileList, type DroppedEntry,
} from "./drive-upload-utils";

type UploadInput = { file: File; relativePath: string };
type ToastSetter = Dispatch<SetStateAction<string | null>>;

type UseDriveUploadIntakeOptions = {
  currentFolderId: number | null;
  listView: DriveListView | null;
  loadItems: (folderId: number | null, view: DriveListView, queryOverride?: string) => Promise<void>;
  setToast: ToastSetter;
  setFileDropActive: Dispatch<SetStateAction<boolean>>;
  setDropTargetFolderId: Dispatch<SetStateAction<number | null>>;
  autoScrollDuringInternalDrag: (event: DragEvent<HTMLElement>) => void;
};

/**
 * Điều phối các nguồn nhập file (bộ chọn, kéo thả từ máy, clipboard) và đưa vào UploadManager.
 * Chỉ chuẩn bị cấu trúc thư mục / hàng đợi; quá trình upload vẫn do UploadManager thực hiện.
 * Kéo thả mục đã tồn tại trong Drive được phân biệt với upload từ hệ điều hành.
 */
export default function useDriveUploadIntake({
  currentFolderId, listView, loadItems, setToast, setFileDropActive,
  setDropTargetFolderId, autoScrollDuringInternalDrag,
}: UseDriveUploadIntakeOptions) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const pasteHandlerRef = useRef<(files: readonly UploadInput[]) => void>(() => {});
  const [dragMessage, setDragMessage] = useState("Drop files to upload");
  const { enqueue, openManager } = useUploadManager();

  useEffect(() => {
    function handleUploadCompleted(event: Event) {
      const detail = (event as CustomEvent<{ destinationId: string | null }>).detail;
      if (!detail || !listView) return;

      // Dung lượng và cây thư mục là dữ liệu tổng hợp có cache; sau khi upload xong
      // phải phát tín hiệu cập nhật, kể cả khi tệp nằm ở một thư mục khác.
      window.dispatchEvent(new Event(FOLDER_TREE_REFRESH_EVENT));
      if (listView === "drive") {
        const currentDestinationId = currentFolderId === null ? null : String(currentFolderId);
        if (detail.destinationId !== currentDestinationId) return;
        void loadItems(currentFolderId, "drive");
        return;
      }

      // Danh sách Recent cũng cần được cập nhật khi có tệp vừa upload.
      if (listView === "recent") {
        void loadItems(null, "recent");
      }
    }

    window.addEventListener(DRIVE_UPLOAD_COMPLETED_EVENT, handleUploadCompleted);
    return () => window.removeEventListener(DRIVE_UPLOAD_COMPLETED_EVENT, handleUploadCompleted);
  }, [currentFolderId, listView, loadItems]);

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

    // Đường dẫn thư mục trong hàng đợi phải trỏ đến bản ghi Folder thật.
    // Xác định ID thư mục cha trước khi tạo nhiệm vụ upload cho file.
    const folderIdsByPath = new Map<string, string>();
    const createdOrReusedFolderIds = new Set<string>();
    const ensureFolder = async (name: string, parentId: string | null): Promise<string> => {
      const cacheKey = `${parentId ?? "root"}::${name.toLocaleLowerCase()}`;
      const cached = folderIdsByPath.get(cacheKey);
      if (cached) return cached;

      // Tái sử dụng thư mục cùng tên ở đúng thư mục cha để tránh trùng lặp.
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
      // Xử lý tuần tự để hai file cùng thư mục cha mới không tạo bản ghi trùng nhau.
      for (const entry of normalizedFiles) {
        // File có đường dẫn không hợp lệ vẫn được đưa vào hàng đợi ở trạng thái lỗi,
        // nhưng không được tạo thư mục từ đoạn đường dẫn nguy hiểm.
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
        window.dispatchEvent(new Event(FOLDER_TREE_REFRESH_EVENT));
        if (listView === "drive") await loadItems(currentFolderId, "drive");
      }
      openManager();
    } catch (error) {
      setToast(error instanceof Error
        ? `Could not prepare the folder structure. No files were queued. ${error.message}`
        : "Could not prepare the folder structure. No files were queued.");
    }
  }, [currentFolderId, enqueue, listView, loadItems, openManager, setToast]);

  function handleSelectedFiles(fileList: FileList | null) {
    if (!fileList) return;
    const selected = Array.from(fileList).map((file) => ({
      file,
      relativePath: file.webkitRelativePath || file.name,
    }));
    void addUploadFiles(selected);
  }

  const openFolderPicker = useCallback(() => {
    const input = folderInputRef.current;
    if (!input) return;
    if (!("webkitdirectory" in input)) {
      setToast("Folder selection isn't supported by this browser. Use Upload files and select files individually.");
      return;
    }
    input.click();
  }, [setToast]);

  useEffect(() => {
    function onUploadFiles() { fileInputRef.current?.click(); }
    function onUploadFolder() { openFolderPicker(); }
    function onFilePickerCancel() {
      setToast("File selection canceled. Nothing was added to the queue.");
    }
    window.addEventListener(DRIVE_UPLOAD_FILES_EVENT, onUploadFiles);
    window.addEventListener(DRIVE_UPLOAD_FOLDER_EVENT, onUploadFolder);
    const fileInput = fileInputRef.current;
    const folderInput = folderInputRef.current;
    fileInput?.addEventListener("cancel", onFilePickerCancel);
    folderInput?.addEventListener("cancel", onFilePickerCancel);
    return () => {
      window.removeEventListener(DRIVE_UPLOAD_FILES_EVENT, onUploadFiles);
      window.removeEventListener(DRIVE_UPLOAD_FOLDER_EVENT, onUploadFolder);
      fileInput?.removeEventListener("cancel", onFilePickerCancel);
      folderInput?.removeEventListener("cancel", onFilePickerCancel);
    };
  }, [openFolderPicker, setToast]);

  // Listener dán file chỉ đăng ký một lần; ref luôn trỏ đến bộ xử lý hiện hành.
  useEffect(() => { pasteHandlerRef.current = addUploadFiles; }, [addUploadFiles]);

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
      // Trình duyệt có thể trả cùng một file trong files và items: chỉ lấy một nguồn.
      const files = preferClipboardFileList(fromFiles, fromItems);
      if (!files.length) return;
      event.preventDefault();
      pasteHandlerRef.current(files.map((file) => ({ file, relativePath: file.name })));
      setToast(`${files.length} file${files.length === 1 ? "" : "s"} pasted from clipboard and added to uploads.`);
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [setToast]);

  function handleDragEnter(event: DragEvent<HTMLElement>) {
    const kind = getDriveDropKind(event.dataTransfer.types, ITEM_DRAG_TYPE);
    if (kind === "internal") {
      // Kéo thả nội bộ thuộc nhóm Move; không phủ lớp Upload lên giao diện.
      event.preventDefault();
      return;
    }
    if (kind !== "files") return;

    event.preventDefault();
    const hasDirectory = Array.from(event.dataTransfer.items).some(
      (item) => getDroppedEntry(item)?.isDirectory,
    );
    setDragMessage(hasDirectory ? "Drop folder to prepare files" : "Drop files to upload");
    setFileDropActive(true);
  }

  function handleDragLeave(event: DragEvent<HTMLElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setFileDropActive(false);
  }

  function handleDragOver(event: DragEvent<HTMLElement>) {
    const kind = getDriveDropKind(event.dataTransfer.types, ITEM_DRAG_TYPE);
    if (kind === "internal") {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      autoScrollDuringInternalDrag(event);
      return;
    }
    if (kind !== "files") return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setFileDropActive(true);
  }

  async function handleDrop(event: DragEvent<HTMLElement>) {
    const kind = getDriveDropKind(event.dataTransfer.types, ITEM_DRAG_TYPE);
    if (kind === "unsupported") {
      event.preventDefault();
      setFileDropActive(false);
      setToast("This item type cannot be added to the upload queue.");
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setFileDropActive(false);
    if (kind === "internal") {
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

  return {
    fileInputRef, folderInputRef, dragMessage,
    handleSelectedFiles, handleDragEnter, handleDragLeave, handleDragOver, handleDrop,
  };
}
