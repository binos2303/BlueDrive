import type { RenameTarget } from "@/lib/drive-service";
import type { DriveItem } from "./types";

/** Giữ nguyên quy tắc chuẩn hóa ID thư mục và kiểm tra quyền đổi tên. */
export function renameTargetForSelection(targets: readonly DriveItem[], title: string): RenameTarget | null {
  if (targets.length !== 1 || targets[0].canManage === false || title === "Trash") return null;
  const target = targets[0];
  return {
    kind: target.type === "folder" ? "folder" : "file",
    id: target.type === "folder" ? (target.folderId ?? Math.abs(target.id)) : target.id,
    name: target.name,
  };
}

type DuplicateDependencies = {
  postItemAction: (targets: DriveItem[]) => Promise<{ detail: string }>;
  clearSelectedIds: () => void;
  notifyFolderTreeChanged: () => void;
  refreshItems: () => Promise<void>;
  setToast: (message: string) => void;
};

/** Sau khi nhân bản: gọi API → bỏ chọn → làm mới cây thư mục → tải danh sách → thông báo. */
export async function executeDuplicateItems(targets: DriveItem[], dependencies: DuplicateDependencies) {
  try {
    const result = await dependencies.postItemAction(targets);
    dependencies.clearSelectedIds();
    dependencies.notifyFolderTreeChanged();
    await dependencies.refreshItems();
    dependencies.setToast(result.detail || "Duplicate created successfully.");
  } catch (error) {
    dependencies.setToast(error instanceof Error ? error.message : "Could not duplicate selected items.");
  }
}


/** Chỉ cập nhật đúng mục được chọn (cả ID lẫn loại); không sửa mảng nguồn. */
export function applyStarredToItems(
  current: readonly DriveItem[],
  targets: readonly DriveItem[],
  starred: boolean,
): DriveItem[] {
  return current.map((item) => {
    const matched = targets.some((selected) => selected.id === item.id && selected.type === item.type);
    return matched ? { ...item, starred } : item;
  });
}


/** Quyết định endpoint theo thao tác đã xác nhận; tuyệt đối không tráo Trash với xóa vĩnh viễn. */
export function destructiveActionConfig(action: "trash" | "delete") {
  return action === "trash"
    ? { path: "/drive/api/items/trash/", defaultMessage: "Moved to Trash." }
    : { path: "/drive/api/items/delete/", defaultMessage: "Permanently deleted." };
}
