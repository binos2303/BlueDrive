"use client";

import type React from "react";
import { GripVertical, MoreHorizontal, Star } from "lucide-react";
import ContextMenu, { type ContextMenuAction } from "@/components/ui/ContextMenu";
import { renderItemIcon } from "./DriveItemIcon";
import type { DriveItem } from "./types";

type DriveGridProps = {
  folderItems: DriveItem[];
  fileItems: DriveItem[];
  selectedIds: Set<number>;
  title: string;
  dropTargetFolderId: number | null;
  onItemClick: (event: React.MouseEvent<HTMLElement>, id: number) => void;
  onOpen: (item: DriveItem) => void;
  onToggleItem: (id: number) => void;
  onToggleStar: (items: DriveItem[]) => Promise<void>;
  createActions: (item?: DriveItem) => ContextMenuAction[];
  onDragStart: (event: React.DragEvent<HTMLButtonElement>, item: DriveItem) => void;
  onDragEnd: () => void;
  onFolderDragOver: (event: React.DragEvent<HTMLElement>, item: DriveItem) => void;
  onDropOnFolder: (event: React.DragEvent<HTMLElement>, item: DriveItem) => Promise<void>;
};

export default function DriveGrid({
  folderItems, fileItems, selectedIds, title, dropTargetFolderId, onItemClick,
  onOpen, onToggleItem, onToggleStar, createActions, onDragStart, onDragEnd,
  onFolderDragOver, onDropOnFolder,
}: DriveGridProps) {
  return (
          <div className="space-y-5 p-3 sm:p-4">
            {folderItems.length > 0 && (
              <section aria-labelledby="drive-folders-heading" data-marquee-section="folders">
                <div data-no-marquee-selection="true" className="mb-2 flex items-center justify-between px-1">
                  <h3 id="drive-folders-heading" className="text-sm font-semibold text-foreground">Folders</h3>
                  <span className="text-xs text-muted">{folderItems.length}</span>
                </div>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,20rem),1fr))] gap-3">
                  {folderItems.map((item) => {
                    const selected = selectedIds.has(item.id);
                    return (
                      <article
                        key={item.id}
                        data-drive-item-id={item.id}
                        onClick={(event) => onItemClick(event, item.id)}
                        onDoubleClick={() => onOpen(item)}
                        onDragOver={(event) => onFolderDragOver(event, item)}
                        onDrop={(event) => void onDropOnFolder(event, item)}
                        role="button"
                        aria-pressed={selected}
                        tabIndex={0}
                        onKeyDown={(event) => {
                          if (event.target !== event.currentTarget) return;
                          if (event.key === "Enter") onOpen(item);
                          if (event.key === " ") { event.preventDefault(); onToggleItem(item.id); }
                        }}
                        className={`flex h-14 min-w-0 items-center gap-2 rounded-xl border px-3 transition-colors duration-(--motion-fast) ${selected ? "border-brand-contrast bg-brand-soft ring-1 ring-brand-contrast/20" : "border-border bg-background hover:border-border-strong hover:bg-brand-soft/40"} ${dropTargetFolderId === item.folderId ? "ring-2 ring-brand-contrast bg-brand-soft" : ""}`}
                      >
                        <button
                          type="button"
                          draggable
                          data-no-marquee-selection="true"
                          onClick={(event) => event.stopPropagation()}
                          onPointerDown={(event) => event.stopPropagation()}
                          onDragStart={(event) => onDragStart(event, item)}
                          onDragEnd={() => { onDragEnd(); }}
                          aria-label={`Drag ${item.name}`}
                          title="Drag to move"
                          className="ui-control flex h-9 w-7 shrink-0 cursor-grab items-center justify-center text-muted active:cursor-grabbing"
                        >
                          <GripVertical size={14} />
                        </button>
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand-contrast">
                          {renderItemIcon("folder", 18)}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-left text-sm font-medium text-foreground" title={item.name}>
                          {item.name}
                        </span>
                        {title !== "Trash" && (
                          <button
                            type="button"
                            aria-label={item.starred ? `Remove ${item.name} from Starred` : `Add ${item.name} to Starred`}
                            title={item.starred ? "Remove from Starred" : "Add to Starred"}
                            onPointerDown={(event) => event.stopPropagation()}
                            onClick={(event) => { event.stopPropagation(); void onToggleStar([item]); }}
                            className={`ui-control flex h-10 w-10 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-brand-soft ${item.starred ? "text-warning" : "text-muted opacity-60 hover:opacity-100"}`}
                          >
                            <Star size={15} fill={item.starred ? "currentColor" : "none"} />
                          </button>
                        )}
                        <span
                          onPointerDown={(event) => event.stopPropagation()}
                          onClick={(event) => event.stopPropagation()}
                          onDoubleClick={(event) => event.stopPropagation()}
                        >
                          <ContextMenu
                            label={`Actions for ${item.name}`}
                            trigger={<MoreHorizontal size={16} />}
                            actions={createActions(item)}
                          />
                        </span>
                      </article>
                    );
                  })}
                </div>
              </section>
            )}

            {fileItems.length > 0 && (
              <section aria-labelledby="drive-files-heading" data-marquee-section="files" className={folderItems.length > 0 ? "pt-1" : ""}>
                <div data-no-marquee-selection="true" className="mb-2 flex items-center justify-between px-1">
                  <h3 id="drive-files-heading" className="text-sm font-semibold text-foreground">Files</h3>
                  <span className="text-xs text-muted">{fileItems.length}</span>
                </div>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,20rem),1fr))] gap-3">
                  {fileItems.map((item) => {
                    const selected = selectedIds.has(item.id);
                    return (
                      <article
                        key={item.id}
                        data-drive-item-id={item.id}
                        onClick={(event) => onItemClick(event, item.id)}
                        onDoubleClick={() => onOpen(item)}
                        role="button"
                        aria-pressed={selected}
                        tabIndex={0}
                        onKeyDown={(event) => {
                          if (event.target !== event.currentTarget) return;
                          if (event.key === "Enter") onOpen(item);
                          if (event.key === " ") { event.preventDefault(); onToggleItem(item.id); }
                        }}
                        className={`min-w-0 cursor-pointer rounded-xl border p-3 transition-colors duration-(--motion-fast) ${selected ? "border-brand-contrast bg-brand-soft/60 ring-1 ring-brand-contrast/20" : "border-border bg-surface hover:border-brand/30 hover:bg-brand-soft/25"}`}
                      >
                        <div className="flex min-w-0 items-center gap-1.5">
                          <button
                            type="button"
                            draggable
                            data-no-marquee-selection="true"
                            onClick={(event) => event.stopPropagation()}
                            onPointerDown={(event) => event.stopPropagation()}
                            onDragStart={(event) => onDragStart(event, item)}
                            onDragEnd={() => { onDragEnd(); }}
                            aria-label={`Drag ${item.name}`}
                            title="Drag to move"
                            className="ui-control flex h-6 w-5 shrink-0 cursor-grab items-center justify-center text-muted active:cursor-grabbing"
                          >
                            <GripVertical size={14} />
                          </button>
                          <span className="ui-control flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand-contrast">
                            {renderItemIcon(item.type, 16)}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-left text-sm font-medium text-foreground" title={item.name}>
                            {item.name}
                          </span>
                          {title !== "Trash" && (
                            <button
                              type="button"
                              aria-label={item.starred ? `Remove ${item.name} from Starred` : `Add ${item.name} to Starred`}
                              title={item.starred ? "Remove from Starred" : "Add to Starred"}
                              onPointerDown={(event) => event.stopPropagation()}
                              onClick={(event) => { event.stopPropagation(); void onToggleStar([item]); }}
                              className={`ui-control flex h-10 w-10 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-brand-soft ${item.starred ? "text-warning" : "text-muted opacity-60 hover:opacity-100"}`}
                            >
                              <Star size={15} fill={item.starred ? "currentColor" : "none"} />
                            </button>
                          )}
                          <span
                            onPointerDown={(event) => event.stopPropagation()}
                            onClick={(event) => event.stopPropagation()}
                            onDoubleClick={(event) => event.stopPropagation()}
                          >
                            <ContextMenu
                              label={`Actions for ${item.name}`}
                              trigger={<MoreHorizontal size={16} />}
                              actions={createActions(item)}
                            />
                          </span>
                        </div>
                        <div className="mt-3 flex items-center justify-between gap-2 pl-13 text-xs text-muted">
                          <span className="min-w-0 truncate" title="Date modified">{item.modified}</span>
                          <span className="shrink-0">{item.size}</span>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </section>
            )}

          </div>
  );
}
