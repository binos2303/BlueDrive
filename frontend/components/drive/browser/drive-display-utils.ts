import type { DriveListView } from "@/lib/drive-service";
import type { DriveItem, SortDirection, SortKey } from "./types";

export function listViewForTitle(title: string): DriveListView | null {
  if (title === "My Drive" || title === "Workspace files") return "drive";
  if (title === "Recent") return "recent";
  if (title === "Trash") return "trash";
  if (title === "Shared with me") return "shared";
  if (title === "Starred") return "starred";
  return null;
}

export function parseSize(value: string) {
  const match = value.match(/^([\d.]+)\s*(B|KB|MB|GB|TB)$/i);
  if (!match) return 0;
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unitIndex = units.indexOf(match[2].toUpperCase());
  return Number(match[1]) * 1024 ** unitIndex;
}


/** Match the original Drive browser order: folders first, then the requested sort. */
export function sortDriveItems(
  items: readonly DriveItem[],
  sortKey: SortKey,
  sortDirection: SortDirection,
): DriveItem[] {
  return [...items].sort((first, second) => {
    // Folder grouping never changes when the sort direction changes.
    const firstIsFolder = first.type === "folder";
    const secondIsFolder = second.type === "folder";
    if (firstIsFolder !== secondIsFolder) return firstIsFolder ? -1 : 1;

    let comparison: number;
    if (sortKey === "modified") {
      const firstTime = Date.parse(first.modifiedAt ?? "");
      const secondTime = Date.parse(second.modifiedAt ?? "");
      // Unknown dates stay last in either direction; localized labels are display-only.
      if (!Number.isFinite(firstTime)) return Number.isFinite(secondTime) ? 1 : 0;
      if (!Number.isFinite(secondTime)) return -1;
      comparison = firstTime - secondTime;
    } else if (sortKey === "size") {
      comparison = parseSize(first.size) - parseSize(second.size);
    } else if (sortKey === "type") {
      comparison = first.type.localeCompare(second.type);
    } else {
      comparison = first.name.localeCompare(second.name, undefined, { numeric: true });
    }
    return sortDirection === "asc" ? comparison : -comparison;
  });
}
