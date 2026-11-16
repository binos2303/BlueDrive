export type SortDirection = "asc" | "desc";
export type SortKey = "name" | "modified" | "size" | "type";
export type DriveItemType = "folder" | "document" | "image";
export type DriveItem = {
  id: number;
  folderId?: number;
  name: string;
  owner: string;
  ownerInitials: string;
  modified: string;
  modifiedAt?: string;
  size: string;
  type: DriveItemType;
  starred?: boolean;
  canManage?: boolean;
};


