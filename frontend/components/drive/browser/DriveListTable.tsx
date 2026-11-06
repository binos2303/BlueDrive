"use client";

import type React from "react";
import { ArrowDown, ArrowUp, GripVertical, MoreHorizontal, Star } from "lucide-react";
import ContextMenu, { type ContextMenuAction } from "@/components/ui/ContextMenu";
import { renderItemIcon } from "./DriveItemIcon";
import type { DriveItem, SortDirection, SortKey } from "./types";

type DriveListTableProps = {
  items: DriveItem[];
  selectedIds: Set<number>;
  sortKey: SortKey;
  sortDirection: SortDirection;
  onSort: (field: SortKey) => void;
  onItemClick: (event: React.MouseEvent<HTMLElement>, id: number) => void;
  onOpen: (item: DriveItem) => void;
  onToggleStar: (items: DriveItem[]) => Promise<void>;
  showStar: boolean;
  createActions: (item?: DriveItem) => ContextMenuAction[];
  onDragStart: (event: React.DragEvent<HTMLButtonElement>, item: DriveItem) => void;
  onDragEnd: () => void;
  onFolderDragOver: (event: React.DragEvent<HTMLElement>, item: DriveItem) => void;
  onDropOnFolder: (event: React.DragEvent<HTMLElement>, item: DriveItem) => Promise<void>;
  dropTargetFolderId: number | null;
};

export default function DriveListTable({
  items, selectedIds, sortKey, sortDirection, onSort, onItemClick, onOpen,
  onToggleStar, showStar, createActions, onDragStart, onDragEnd,
  onFolderDragOver, onDropOnFolder, dropTargetFolderId,
}: DriveListTableProps) {
  return (
          <div className="min-w-0">
            <table className="w-full min-w-3xl border-separate border-spacing-0 text-left">
              <thead>
                <tr className="bg-background text-[13px] font-semibold text-muted">
                  <SortableHeading label="Name" field="name" current={sortKey} direction={sortDirection} onSort={onSort} />
                  <th scope="col" className="sticky top-0 z-20 border-b border-border bg-background px-4 py-3">Owner</th>
                  <SortableHeading label="Date modified" field="modified" current={sortKey} direction={sortDirection} onSort={onSort} />
                  <SortableHeading label="File size" field="size" current={sortKey} direction={sortDirection} onSort={onSort} />
                  <th scope="col" className="sticky top-0 z-20 w-20 border-b border-border bg-background px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <FileRow
                    key={item.id}
                    item={item}
                    selected={selectedIds.has(item.id)}
                    onToggle={(event) => onItemClick(event, item.id)}
                    onOpen={() => onOpen(item)}
                    onToggleStar={() => void onToggleStar([item])}
                    showStar={showStar}
                    actions={createActions(item)}
                    onDragStart={(event) => onDragStart(event, item)}
                    onDragEnd={() => { onDragEnd(); }}
                    onDragOverItem={(event) => onFolderDragOver(event, item)}
                    onDropOnItem={(event) => void onDropOnFolder(event, item)}
                    dropTarget={item.type === "folder" && item.folderId === dropTargetFolderId}
                  />
                ))}
              </tbody>
            </table>
            <div aria-hidden="true" className="h-12 select-none" />
          </div>
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
    <th scope="col" aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"} className="sticky top-0 z-20 border-b border-border bg-background px-4 py-2">
      <button
        type="button"
        onClick={() => onSort(field)}
        className="inline-flex min-h-9 items-center gap-2 rounded-lg text-left transition-colors duration-(--motion-fast) hover:text-brand-contrast"
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
  onToggleStar,
  showStar,
  actions,
  onDragStart,
  onDragEnd,
  onDragOverItem,
  onDropOnItem,
  dropTarget,
}: {
  item: DriveItem;
  selected: boolean;
  onToggle: (event: React.MouseEvent<HTMLTableRowElement>) => void;
  onOpen: () => void;
  onToggleStar: () => void;
  showStar: boolean;
  actions: ContextMenuAction[];
  onDragStart: (event: React.DragEvent<HTMLButtonElement>) => void;
  onDragEnd: () => void;
  onDragOverItem: (event: React.DragEvent<HTMLTableRowElement>) => void;
  onDropOnItem: (event: React.DragEvent<HTMLTableRowElement>) => void;
  dropTarget: boolean;
}) {
  return (
    <tr
      data-drive-item-id={item.id}
      aria-selected={selected}
      onClick={onToggle}
      onDoubleClick={() => onOpen()}
      onDragOver={onDragOverItem}
      onDrop={onDropOnItem}
      className={`cursor-pointer transition-colors duration-(--motion-fast) ${selected ? "bg-brand-soft/60" : "hover:bg-brand-soft/25"} ${dropTarget ? "bg-brand-soft ring-2 ring-inset ring-brand-contrast" : ""}`}
    >
      <th scope="row" className="max-w-[24rem] border-b border-border px-3 py-2 text-left font-normal">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            draggable
            onClick={(event) => event.stopPropagation()}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            aria-label={`Drag ${item.name}`}
            data-no-marquee-selection="true"
            onPointerDown={(event) => event.stopPropagation()}
            title="Drag to move"
            className="flex h-9 w-7 shrink-0 cursor-grab items-center justify-center rounded-lg text-muted transition-colors hover:bg-brand-soft hover:text-brand-contrast active:cursor-grabbing focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-contrast"
          >
            <GripVertical size={16} />
          </button>
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-brand-soft text-brand-contrast">
            {renderItemIcon(item.type, 19)}
          </span>
          <span className="min-w-0 truncate rounded text-left text-sm text-foreground" title={item.name}>
            {item.name}
          </span>
          {showStar && (
            <button
              type="button"
              aria-label={item.starred ? `Remove ${item.name} from Starred` : `Add ${item.name} to Starred`}
              title={item.starred ? "Remove from Starred" : "Add to Starred"}
              data-no-marquee-selection="true"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => { event.stopPropagation(); onToggleStar(); }}
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-brand-soft ${item.starred ? "text-amber-500" : "text-muted opacity-60 hover:opacity-100"}`}
            >
              <Star size={15} fill={item.starred ? "currentColor" : "none"} />
            </button>
          )}
        </div>
      </th>
      <td className="border-b border-border px-4 py-2">
        <span className="inline-flex min-h-10 items-center gap-2 text-sm text-foreground">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[10px] font-semibold text-brand-contrast">
            {item.ownerInitials}
          </span>
          <span className="truncate text-sm">{item.owner}</span>
        </span>
      </td>
      <td className="whitespace-nowrap border-b border-border px-4 py-2 text-sm text-foreground">{item.modified}</td>
      <td className="whitespace-nowrap border-b border-border px-4 py-2 text-sm text-foreground">{item.size}</td>
      <td className="border-b border-border px-3 py-2 text-right" onClick={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()}>
        <ContextMenu
          label={`Actions for ${item.name}`}
          trigger={<MoreHorizontal size={18} />}
          actions={actions}
        />
      </td>
    </tr>
  );
}