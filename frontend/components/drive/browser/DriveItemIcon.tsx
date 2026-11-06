import type { ReactNode } from "react";
import { FileText, Folder, Image as ImageIcon } from "lucide-react";
import type { DriveItemType } from "./types";

export function renderItemIcon(type: DriveItemType, size: number): ReactNode {
  if (type === "folder") return <Folder size={size} />;
  if (type === "image") return <ImageIcon size={size} />;
  return <FileText size={size} />;
}

