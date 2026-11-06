"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import {
  getDriveFolderDetails,
  getDriveItems,
  type DriveFolderDetails,
  type DriveListView,
} from "@/lib/drive-service";
import type { DriveItem, SortDirection, SortKey } from "./types";
import { sortDriveItems } from "./drive-display-utils";

/**
 * Owns the list, loading/error state, sorting and search query for one Drive view.
 * Route/event lifecycle and mutations remain with DriveFileBrowser in Stage B2.
 */
export default function useDriveItems(initialItems: DriveItem[], listView: DriveListView | null) {
  const [driveItems, setDriveItems] = useState(initialItems);
  const [searchQuery, setSearchQuery] = useState("");
  // Event handlers must see the latest query even before React renders.
  const searchQueryRef = useRef("");
  const [loading, setLoading] = useState(listView !== null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [folderDetails, setFolderDetails] = useState<DriveFolderDetails | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  // A newer request always wins, including across search/workspace changes.
  const loadRequestIdRef = useRef(0);

  const sortedItems = useMemo(
    () => sortDriveItems(driveItems, sortKey, sortDirection),
    [driveItems, sortKey, sortDirection],
  );
  const folderItems = useMemo(
    () => sortedItems.filter((item) => item.type === "folder"),
    [sortedItems],
  );
  const fileItems = useMemo(
    () => sortedItems.filter((item) => item.type !== "folder"),
    [sortedItems],
  );

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

  return {
    driveItems, setDriveItems,
    searchQuery, setSearchQuery, searchQueryRef,
    loading, loadError, folderDetails, setFolderDetails,
    sortKey, setSortKey, sortDirection, setSortDirection,
    sortedItems, folderItems, fileItems,
    loadItems,
  };
}
