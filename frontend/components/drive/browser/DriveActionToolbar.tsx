"use client";

import { ArrowDown, ArrowUp, ChevronDown, Copy, Download, FolderOpen, ListFilter, Move, Pencil, RotateCcw, Share2, Star, Trash2, X } from "lucide-react";
import type { DriveItem, SortDirection, SortKey } from "./types";

type DriveActionToolbarProps = {
  title: string;
  selectedItems: DriveItem[];
  selectedCanManage: boolean;
  selectedCanShare: boolean;
  isMovingItems: boolean;
  isDuplicatingItems: boolean;
  sortKey: SortKey;
  sortDirection: SortDirection;
  itemCount: number;
  hasListView: boolean;
  onClearSelection: () => void;
  onRestoreSelected: () => void;
  onRunAction: (action: string, item?: DriveItem) => void;
  onToggleStarSelected: () => void;
  onPendingDelete: (action: "trash" | "delete") => void;
  onSortKeyChange: (key: SortKey) => void;
  onToggleSortDirection: () => void;
};

export default function DriveActionToolbar({
  title, selectedItems, selectedCanManage, selectedCanShare, isMovingItems,
  isDuplicatingItems, sortKey, sortDirection, itemCount, hasListView,
  onClearSelection, onRestoreSelected, onRunAction, onToggleStarSelected,
  onPendingDelete, onSortKeyChange, onToggleSortDirection,
}: DriveActionToolbarProps) {
  // Keep both toolbars in the same fixed-height slot to prevent layout shifts.
  return (
      <div className="drive-toolbar relative my-2 h-12">
        <div
          role="toolbar"
          aria-label="Selected file actions"
          aria-hidden={selectedItems.length === 0}
          inert={selectedItems.length === 0}
          className={`absolute inset-0 flex h-full min-w-0 flex-nowrap items-center gap-1 overflow-x-auto rounded-xl bg-brand-soft px-1.5 sm:gap-1.5 sm:px-2 transition-[opacity,transform,visibility] duration-200 ease-out motion-reduce:transition-none ${selectedItems.length > 0
            ? "visible translate-y-0 scale-100 opacity-100"
            : "invisible pointer-events-none -translate-y-1 scale-[0.985] opacity-0"
          }`}
        >
          <button
            type="button"
            aria-label="Clear selection"
            title="Clear selection"
            onClick={onClearSelection}
            className="ui-control inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
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
              onClick={onRestoreSelected}
              className="ui-control inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
            >
              <RotateCcw size={16} />
            </button>
          )}
          <button
            type="button"
            aria-label="Open"
            title="Open"
            onClick={() => onRunAction("Open", selectedItems[0])}
            disabled={selectedItems.length !== 1}
            className="ui-control inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
          >
            <FolderOpen size={16} />
          </button>
          <button
            type="button"
            aria-label="Download"
            title="Download"
            onClick={() => onRunAction("Download")}
            className="ui-control inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
          >
            <Download size={16} />
          </button>
          <button
            type="button"
            aria-label="Rename"
            title="Rename"
            onClick={() => onRunAction("Rename")}
            disabled={selectedItems.length !== 1 || !selectedCanManage}
            className="ui-control inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
          >
            <Pencil size={16} />
          </button>
          {title !== "Shared with me" && title !== "Trash" && (
            <>
              <button
                type="button"
                aria-label={isMovingItems ? "Moving items" : "Move"}
                title={isMovingItems ? "Moving items…" : "Move"}
                onClick={() => onRunAction("Move")}
                disabled={isMovingItems || isDuplicatingItems || !selectedCanManage}
                className="ui-control inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
              >
                <Move size={16} />
              </button>
              <button
                type="button"
                aria-label={isDuplicatingItems ? "Duplicating items" : "Duplicate"}
                title={isDuplicatingItems ? "Duplicating items…" : "Duplicate"}
                onClick={() => onRunAction("Duplicate")}
                disabled={isDuplicatingItems || isMovingItems || !selectedCanManage}
                className="ui-control inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
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
              onClick={() => onToggleStarSelected()}
              className="ui-control inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
            >
              <Star size={16} fill={selectedItems.every((item) => item.starred) ? "currentColor" : "none"} />
            </button>
          )}
          {title !== "Shared with me" && title !== "Trash" && selectedCanShare && (
            <button
              type="button"
              aria-label="Share"
              title="Share"
              onClick={() => onRunAction("Share")}
              className="ui-control inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
            >
              <Share2 size={16} />
            </button>
          )}
          {(title === "Trash" || (title !== "Shared with me" && selectedCanManage)) && (
            <button
              type="button"
              aria-label={title === "Trash" ? "Delete permanently" : "Move to trash"}
              title={title === "Trash" ? "Delete permanently" : "Move to trash"}
              onClick={() => onPendingDelete(title === "Trash" ? "delete" : "trash")}
              className="ui-control inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-danger transition-colors hover:bg-danger/10 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-danger"
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
              onChange={(event) => onSortKeyChange(event.target.value as SortKey)}
              className="h-10 appearance-none rounded-lg border border-border bg-surface py-1.5 pl-3 pr-8 text-[13px] text-foreground transition-colors hover:bg-background focus-visible:border-brand-contrast"
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
            onClick={() => onToggleSortDirection()}
            className="flex h-10 shrink-0 items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 text-[13px] text-foreground transition-colors duration-(--motion-fast) hover:bg-background"
            aria-label={`Sort ${sortKey} ${sortDirection === "asc" ? "descending" : "ascending"}`}
          >
            <ListFilter size={15} className="text-muted" />
            <span>{sortDirection === "asc" ? "Ascending" : "Descending"}</span>
            {sortDirection === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
          </button>
          <span className="ml-auto shrink-0 whitespace-nowrap text-xs font-medium text-muted" aria-live="polite">
            {hasListView ? `${itemCount} items` : title === "Starred" ? "No starred items yet" : "Demo UI · file actions not connected"}
          </span>
        </div>
      </div>
  );
}
