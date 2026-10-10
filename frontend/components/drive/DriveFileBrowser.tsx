"use client";

import { useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  FileText,
  Folder,
  Grid2x2,
  Image,
  List,
  ListFilter,
  MoreHorizontal,
} from "lucide-react";

type ViewMode = "list" | "grid";
type SortDirection = "asc" | "desc";
type DriveItemType = "folder" | "document" | "image";

export type DriveItem = {
  id: number;
  name: string;
  owner: string;
  ownerInitials: string;
  modified: string;
  size: string;
  type: DriveItemType;
};

type DriveFileBrowserProps = {
  title: string;
  items: DriveItem[];
};

function getItemIcon(type: DriveItemType) {
  if (type === "folder") return Folder;
  if (type === "image") return Image;
  return FileText;
}

export default function DriveFileBrowser({ title, items }: DriveFileBrowserProps) {
  const [view, setView] = useState<ViewMode>("list");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  const sortedItems = useMemo(
    () =>
      [...items].sort((first, second) => {
        const comparison = first.name.localeCompare(second.name);
        return sortDirection === "asc" ? comparison : -comparison;
      }),
    [items, sortDirection],
  );

  return (
    <section className="m-5 min-h-[calc(100%-40px)] bg-background p-0">
      <div className="flex items-center justify-between gap-4 px-2 pt-2">
        <h1 className="text-[30px] font-normal tracking-[-0.04em] text-foreground">{title}</h1>

        <div className="flex items-center gap-2 rounded-[14px] border border-border bg-background p-1">
          <button
            type="button"
            onClick={() => setView("list")}
            className={[
              "flex h-10 w-10 items-center justify-center rounded-[10px] border border-transparent transition",
              view === "list" ? "bg-brand-soft text-brand shadow-sm" : "text-muted hover:bg-surface hover:text-foreground",
            ].join(" ")}
            aria-label="List view"
            aria-pressed={view === "list"}
          >
            <List size={17} />
          </button>
          <button
            type="button"
            onClick={() => setView("grid")}
            className={[
              "flex h-10 w-10 items-center justify-center rounded-[10px] border border-transparent transition",
              view === "grid" ? "bg-brand-soft text-brand shadow-sm" : "text-muted hover:bg-surface hover:text-foreground",
            ].join(" ")}
            aria-label="Grid view"
            aria-pressed={view === "grid"}
          >
            <Grid2x2 size={17} />
          </button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 px-2 pb-3">
        {["Type", "Last modified", "People"].map((label) => (
          <button
            key={label}
            type="button"
            className="flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-[15px] text-foreground transition hover:bg-background"
          >
            <span>{label}</span>
            <ChevronDown size={15} className="text-muted" />
          </button>
        ))}
        <button
          type="button"
          onClick={() => setSortDirection((current) => (current === "asc" ? "desc" : "asc"))}
          className="ml-auto flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-[15px] text-foreground transition hover:bg-background"
          aria-label={`Sort by name ${sortDirection === "asc" ? "descending" : "ascending"}`}
        >
          <ListFilter size={16} className="text-muted" />
          <span>Sort</span>
          {sortDirection === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
        </button>
      </div>

      {view === "list" ? (
        <div className="overflow-x-auto border-t border-border bg-surface">
          <div className="min-w-[760px]">
            <div className="grid grid-cols-[minmax(0,2.8fr)_minmax(0,1.2fr)_minmax(0,1.2fr)_minmax(0,0.9fr)_52px] items-center gap-4 border-b border-border px-4 py-3 text-[15px] font-medium text-muted">
              <span className="inline-flex items-center gap-2">
                <span>Name</span>
                {sortDirection === "asc" ? (
                  <ArrowUp size={14} className="text-brand" />
                ) : (
                  <ArrowDown size={14} className="text-brand" />
                )}
              </span>
              <span>Owner</span>
              <span>Date modified</span>
              <span>File size</span>
              <span />
            </div>

            {sortedItems.length > 0 ? (
              sortedItems.map((item) => {
                const Icon = getItemIcon(item.type);
                return (
                  <div
                    key={item.id}
                    className="grid grid-cols-[minmax(0,2.8fr)_minmax(0,1.2fr)_minmax(0,1.2fr)_minmax(0,0.9fr)_52px] items-center gap-4 border-b border-border px-4 py-4 text-[15px] transition hover:bg-background last:border-b-0"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-brand-soft text-brand">
                        <Icon size={19} />
                      </div>
                      <span className="truncate text-foreground">{item.name}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[10px] font-semibold text-brand">
                        {item.ownerInitials}
                      </div>
                      <span className="text-foreground">{item.owner}</span>
                    </div>
                    <span className="text-foreground">{item.modified}</span>
                    <span className="text-foreground">{item.size}</span>
                    <div className="flex justify-center">
                      <button
                        type="button"
                        aria-label={`More actions for ${item.name}`}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-muted hover:bg-background hover:text-foreground"
                      >
                        <MoreHorizontal size={18} />
                      </button>
                    </div>
                  </div>
                );
              })
            ) : (
              <p className="px-4 py-10 text-center text-sm text-muted">No items</p>
            )}
          </div>
        </div>
      ) : (
        <div className="mt-1 grid gap-4 border-t border-border pt-5 sm:grid-cols-2 xl:grid-cols-3">
          {sortedItems.length > 0 ? (
            sortedItems.map((item) => {
              const Icon = getItemIcon(item.type);
              return (
                <article key={item.id} className="rounded-2xl border border-border bg-surface p-4 transition hover:bg-background">
                  <div className="flex items-start justify-between">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand">
                      <Icon size={20} />
                    </div>
                    <button
                      type="button"
                      aria-label={`More actions for ${item.name}`}
                      className="flex h-7 w-7 items-center justify-center rounded-md text-muted hover:bg-background hover:text-foreground"
                    >
                      <MoreHorizontal size={18} />
                    </button>
                  </div>
                  <h2 className="mt-4 truncate text-sm font-medium text-foreground">{item.name}</h2>
                  <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted">
                    <span>{item.owner}</span>
                    <span>{item.modified}</span>
                  </div>
                  <p className="mt-2 text-xs text-muted">{item.size}</p>
                </article>
              );
            })
          ) : (
            <p className="col-span-full py-10 text-center text-sm text-muted">No items</p>
          )}
        </div>
      )}
    </section>
  );
}
