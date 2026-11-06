import type { DriveListView } from "@/lib/drive-service";

export function listViewForTitle(title: string): DriveListView | null {
  if (title === "My Drive") return "drive";
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

