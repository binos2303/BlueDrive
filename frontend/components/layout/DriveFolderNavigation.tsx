"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, Folder, type LucideIcon } from "lucide-react";
import { requestAccountApi } from "@/lib/account-service";
import { FOLDER_TREE_REFRESH_EVENT, getActiveWorkspaceIdForRequest } from "@/lib/workspace-context";
import { driveFolderIdFromPathname, drivePath } from "@/lib/drive-paths";

type FolderTreeNode = {
  id: number;
  name: string;
  children: FolderTreeNode[];
};

function collectAncestorIds(nodes: FolderTreeNode[], targetId: number, path: number[] = []): number[] | null {
  for (const node of nodes) {
    const nextPath = [...path, node.id];
    if (node.id === targetId) return nextPath;
    const nested = collectAncestorIds(node.children, targetId, nextPath);
    if (nested) return nested;
  }
  return null;
}

export default function DriveFolderNavigation({ label, icon: Icon, workspaceId, pathname, activeOverride, onNavigate }: {
  label: string;
  icon: LucideIcon;
  workspaceId: string | null;
  pathname: string;
  activeOverride?: boolean;
  onNavigate: () => void;
}) {
  const treeId = useId();
  const [open, setOpen] = useState(false);
  const [folderTree, setFolderTree] = useState<FolderTreeNode[]>([]);
  const [expandedFolders, setExpandedFolders] = useState<Set<number>>(() => new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);
  const rootPath = drivePath(workspaceId);
  const active = activeOverride ?? (pathname === rootPath || driveFolderIdFromPathname(pathname) !== null);

  const refreshFolderTree = useCallback(async () => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const result = await requestAccountApi<{ items: FolderTreeNode[] }>("/drive/api/folder-tree/", { workspaceId });
      if (currentRequest !== requestId.current || workspaceId !== getActiveWorkspaceIdForRequest()) return;
      setFolderTree(result.items ?? []);
    } catch (reason) {
      if (currentRequest !== requestId.current || workspaceId !== getActiveWorkspaceIdForRequest()) return;
      setFolderTree([]);
      setError(reason instanceof Error ? reason.message : "Could not load folders.");
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    const initialRefresh = window.setTimeout(() => { void refreshFolderTree(); }, 0);
    const onRefresh = () => { void refreshFolderTree(); };
    window.addEventListener(FOLDER_TREE_REFRESH_EVENT, onRefresh);
    return () => {
      requestId.current += 1;
      window.clearTimeout(initialRefresh);
      window.removeEventListener(FOLDER_TREE_REFRESH_EVENT, onRefresh);
    };
  }, [refreshFolderTree]);

  function toggleFolder(folderId: number) {
    setExpandedFolders((current) => {
      const next = new Set(current);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  }

  function renderFolderNode(node: FolderTreeNode, depth = 0) {
    const href = drivePath(workspaceId, `folders/${node.id}`);
    const selected = pathname === href || pathname.startsWith(`${href}/`);
    const expanded = expandedFolders.has(node.id);
    return (
      <div key={node.id}>
        <div className={`flex min-h-11 items-center rounded-lg pr-1 transition-colors ${selected ? "bg-brand-soft text-brand-contrast" : "text-muted hover:bg-background hover:text-foreground"}`} style={{ paddingLeft: `${8 + depth * 12}px` }}>
          {node.children.length > 0 ? (
            <button type="button" aria-label={`${expanded ? "Collapse" : "Expand"} ${node.name}`} aria-expanded={expanded}
              onClick={() => toggleFolder(node.id)} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg hover:bg-surface">
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          ) : <span aria-hidden="true" className="w-11 shrink-0" />}
          <Link href={href} onClick={() => {
            const path = collectAncestorIds(folderTree, node.id);
            if (path) setExpandedFolders((current) => new Set([...current, ...path]));
            onNavigate();
          }} aria-current={selected ? "page" : undefined} title={node.name} className="flex min-h-11 min-w-0 flex-1 items-center gap-2 py-1 text-[13px] font-medium">
            <Folder size={14} className="shrink-0" /><span className="truncate">{node.name}</span>
          </Link>
        </div>
        {expanded && node.children.length > 0 && <div>{node.children.map((child) => renderFolderNode(child, depth + 1))}</div>}
      </div>
    );
  }

  return (
    <div>
      <div className={`flex min-h-11 items-center rounded-xl text-sm transition-colors duration-(--motion-fast) ${active ? "bg-brand-soft font-semibold text-brand-contrast" : "font-medium text-muted hover:bg-background hover:text-foreground"}`}>
        <Link href={rootPath} onClick={onNavigate} aria-current={active ? "page" : undefined} className="flex min-h-11 min-w-0 flex-1 items-center gap-3 px-3">
          <Icon size={18} className="shrink-0" /><span>{label}</span>
        </Link>
        <button type="button" aria-label={`${open ? "Collapse" : "Expand"} ${label} folders`} aria-expanded={open} aria-controls={treeId}
          onClick={() => setOpen((current) => !current)} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl hover:bg-surface">
          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>
      </div>
      <div id={treeId} hidden={!open} className="mt-1 space-y-0.5">
        {loading ? <p role="status" className="px-3 py-2 text-xs text-muted">Loading folders…</p>
          : error ? <div className="px-3 py-2"><p role="alert" className="break-words text-xs leading-5 text-danger">{error}</p><button type="button" onClick={() => void refreshFolderTree()} className="mt-1 min-h-11 rounded-lg px-2 text-xs font-medium text-brand-contrast hover:bg-background">Try again</button></div>
            : folderTree.length === 0 ? <p className="px-3 py-2 text-xs text-muted">No folders yet</p>
              : folderTree.map((node) => renderFolderNode(node))}
      </div>
    </div>
  );
}
