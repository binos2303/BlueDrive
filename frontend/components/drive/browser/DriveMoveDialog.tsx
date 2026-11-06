"use client";

import { Folder, FolderOpen } from "lucide-react";
import Button from "@/components/ui/Button";
import type { DriveFolderDetails } from "@/lib/drive-service";
import type { DriveItem } from "./types";

type DriveMoveDialogProps = {
  open: boolean;
  moving: boolean;
  targetCount: number;
  details: DriveFolderDetails | null;
  items: DriveItem[];
  loading: boolean;
  error: string | null;
  destinationId: number | null;
  onClose: () => void;
  onLoadDestination: (id: number | null) => void;
  onConfirm: () => void;
};

export default function DriveMoveDialog({
  open, moving, targetCount, details, items, loading, error, destinationId,
  onClose, onLoadDestination, onConfirm,
}: DriveMoveDialogProps) {
  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-100 flex items-center justify-center bg-black/35 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !moving) onClose();
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="move-items-title"
            className="flex max-h-[min(80vh,680px)] w-full max-w-155 flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl"
          >
            <header className="border-b border-border px-5 py-4">
              <h2 id="move-items-title" className="text-lg font-semibold text-foreground">Move {targetCount} item{targetCount === 1 ? "" : "s"}</h2>
              <p className="mt-1 text-sm text-muted">Choose a destination folder. You can also drag items onto a folder in Drive.</p>
            </header>
            <div className="flex flex-wrap items-center gap-1 border-b border-border px-5 py-3 text-sm">
              <button type="button" onClick={() => onLoadDestination(null)} className="rounded-md px-2 py-1 font-medium text-brand-contrast hover:bg-brand-soft">My Drive</button>
              {(details?.ancestors ?? []).map((ancestor) => (
                <span key={ancestor.id} className="inline-flex items-center gap-1">
                  <span className="text-muted">/</span>
                  <button type="button" onClick={() => onLoadDestination(ancestor.id)} className="rounded-md px-2 py-1 text-brand-contrast hover:bg-brand-soft">{ancestor.name}</button>
                </span>
              ))}
              {details && <span className="inline-flex items-center gap-1"><span className="text-muted">/</span><span className="rounded-md bg-brand-soft px-2 py-1 font-semibold text-brand-contrast">{details.name}</span></span>}
            </div>
            <div className="min-h-55 flex-1 overflow-y-auto p-3">
              {loading ? (
                <div className="flex min-h-40 items-center justify-center text-sm text-muted">Loading folders…</div>
              ) : error ? (
                <div className="rounded-lg border border-danger/30 bg-background p-4 text-sm text-danger" role="alert">
                  <p>{error}</p>
                  <button type="button" onClick={() => onLoadDestination(destinationId)} className="mt-2 font-semibold underline">Try again</button>
                </div>
              ) : items.length === 0 ? (
                <div className="flex min-h-40 flex-col items-center justify-center text-center">
                  <FolderOpen size={28} className="mb-2 text-muted" />
                  <p className="text-sm font-medium text-foreground">No subfolders here</p>
                  <p className="mt-1 text-xs text-muted">Move here will place the selected items in this location.</p>
                </div>
              ) : (
                <ul className="space-y-1">
                  {items.map((folder) => (
                    <li key={folder.id} className="flex items-center gap-2 rounded-lg border border-transparent px-2 py-1.5 hover:border-border hover:bg-background">
                      <Folder size={17} className="shrink-0 text-brand-contrast" />
                      <button type="button" onClick={() => folder.folderId && onLoadDestination(folder.folderId)} className="min-w-0 flex-1 truncate py-1 text-left text-sm text-foreground" title={`Open ${folder.name}`}>{folder.name}</button>
                      <button type="button" disabled={!folder.folderId || loading} onClick={() => folder.folderId && onLoadDestination(folder.folderId)} className="rounded-md px-2 py-1 text-xs font-medium text-brand-contrast hover:bg-brand-soft disabled:opacity-50">Open</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <footer className="flex items-center justify-between gap-3 border-t border-border bg-background px-5 py-4">
              <p className="min-w-0 truncate text-xs text-muted">Destination: {details ? details.location || details.name : "My Drive (root)"}</p>
              <div className="flex shrink-0 items-center gap-2">
                <Button variant="ghost" onClick={() => onClose()} disabled={moving}>Cancel</Button>
                <Button onClick={() => onConfirm()} disabled={moving || loading || Boolean(error)}>
                  {moving ? "Moving…" : "Move here"}
                </Button>
              </div>
            </footer>
          </section>
        </div>
      )}


    </>
  );
}
