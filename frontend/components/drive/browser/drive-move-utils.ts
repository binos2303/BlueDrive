import type { DriveItem } from "./types";

// MIME riêng biệt giúp phân biệt kéo mục Drive với kéo tệp từ hệ điều hành vào để upload.
export const ITEM_DRAG_TYPE = "application/x-securedrive-item";

type BreadcrumbParams = {
  title: string;
  listView: string | null;
  index: number;
  ancestorIds: readonly number[];
  currentFolderId: number | null;
};

/** Trả về undefined nếu breadcrumb không phải điểm thả hợp lệ. null biểu thị thư mục gốc. */
export function getBreadcrumbMoveDestination({
  title, listView, index, ancestorIds, currentFolderId,
}: BreadcrumbParams): number | null | undefined {
  if (title !== "My Drive" || listView !== "drive") return undefined;
  if (index === 0) return null;
  if (index >= 1 && index <= ancestorIds.length) return ancestorIds[index - 1];
  if (index === ancestorIds.length + 1 && currentFolderId !== null) return currentFolderId;
  return undefined;
}

/** Dữ liệu kéo chỉ là tham chiếu UI; quyền và đích di chuyển vẫn phải được backend kiểm tra. */
export function serializeDraggedDriveItems(targets: readonly DriveItem[]): string {
  return JSON.stringify({
    items: targets.map((target) => ({
      id: target.id,
      type: target.type,
      folderId: target.folderId ?? null,
    })),
  });
}

/** Tra mục theo danh sách đang hiển thị, không sử dụng dữ liệu tên/quyền từ payload kéo thả. */
export function resolveDraggedDriveItems(raw: string, available: readonly DriveItem[]): DriveItem[] {
  const parsed = JSON.parse(raw) as { items?: Array<{ id: number }> };
  return (parsed.items ?? [])
    .map((entry) => available.find((candidate) => candidate.id === entry.id))
    .filter((candidate): candidate is DriveItem => candidate !== undefined);
}

type MoveCallbacks = {
  postItemAction: (
    path: string, targets: DriveItem[], extra: Record<string, unknown>,
  ) => Promise<{ detail: string; count?: number }>;
  onMoved?: () => void;
  clearSelectedIds: () => void;
  notifyFolderTreeChanged: () => void;
  refreshItems: () => Promise<void>;
};

/** Giữ nguyên trình tự sau một lệnh Move thành công; lỗi được xử lý bởi hook gọi hàm này. */
export async function executeMoveAndRefresh(
  targets: DriveItem[], destinationFolderId: number | null, callbacks: MoveCallbacks,
): Promise<void> {
  await callbacks.postItemAction("/drive/api/items/move/", targets, {
    destination_folder_id: destinationFolderId,
  });
  callbacks.onMoved?.();
  callbacks.clearSelectedIds();
  callbacks.notifyFolderTreeChanged();
  await callbacks.refreshItems();
}
