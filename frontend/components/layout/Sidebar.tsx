"use client";

import { useCallback, useEffect, useState, type Ref } from "react";
import {
    ChevronDown,
    ChevronRight,
    Clock3,
    Building2,
    Folder,
    HardDrive,
    Share2,
    Star,
    Trash2,
    X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BrandLogo } from "@/components/ui/BrandLogo";
import DriveNewMenu from "@/components/drive/DriveNewMenu";
import WorkspaceSwitcher from "@/components/workspaces/WorkspaceSwitcher";
import { useAccount } from "@/components/account/AccountProvider";
import { DRIVE_UPLOAD_COMPLETED_EVENT, FOLDER_TREE_REFRESH_EVENT, WORKSPACE_CHANGED_EVENT } from "@/lib/workspace-context";
import { requestAccountApi } from "@/lib/account-service";
import { clearActiveWorkspaceSelection, getActiveWorkspaceIdForRequest } from "@/lib/workspace-context";

type FolderTreeNode = {
    id: number;
    name: string;
    parent_id: number | null;
    children: FolderTreeNode[];
};

type SidebarProps = {
    mobileOpen: boolean;
    onNavigate: () => void;
    navigationRef: Ref<HTMLElement>;
};

type QuotaSummary = {
    configured: boolean;
    workspaceName?: string;
    limitBytes: number | null;
    usedBytes: number | null;
    reservedBytes: number | null;
    remainingBytes: number | null;
    percentUsed: number | null;
    message?: string;
    organizationCap?: {
        limitBytes: number | null;
        usedBytes: number;
        reservedBytes: number;
        remainingBytes: number | null;
        percentUsed: number | null;
    };
};

function formatStorageBytes(value: number | null | undefined): string {
    if (value == null) return "—";
    if (value < 1024) return `${value} B`;
    const units = ["KB", "MB", "GB", "TB", "PB"];
    let amount = value / 1024;
    let index = 0;
    while (amount >= 1024 && index < units.length - 1) {
        amount /= 1024;
        index += 1;
    }
    return `${amount.toFixed(amount >= 10 ? 0 : 1)} ${units[index]}`;
}

const navigationItems = [
    { label: "My Drive", href: "/drive", icon: HardDrive },
    { label: "Shared with me", href: "/drive/shared", icon: Share2 },
    { label: "Recent", href: "/drive/recent", icon: Clock3 },
    { label: "Starred", href: "/drive/starred", icon: Star },
    { label: "Trash", href: "/drive/trash", icon: Trash2 },
];

function collectAncestorIds(nodes: FolderTreeNode[], targetId: number, path: number[] = []): number[] | null {
    for (const node of nodes) {
        const nextPath = [...path, node.id];
        if (node.id === targetId) return nextPath;
        const nested = collectAncestorIds(node.children, targetId, nextPath);
        if (nested) return nested;
    }
    return null;
}

export default function Sidebar({ mobileOpen, onNavigate, navigationRef }: SidebarProps) {
    const pathname = usePathname();
    const { state: accountState } = useAccount();
    const account = accountState.status === "loaded" ? accountState.account : null;
    const tenant = account?.account.tenant ?? null;
    const canManageOrganization = Boolean(
        account?.account.type === "business" && tenant && ["owner", "admin"].includes(tenant.role),
    );
    const [folderTree, setFolderTree] = useState<FolderTreeNode[]>([]);
    const [expandedFolders, setExpandedFolders] = useState<Set<number>>(() => new Set());
    const [myDriveExpanded, setMyDriveExpanded] = useState(false);
    const [quota, setQuota] = useState<QuotaSummary | null>(null);
    const [quotaLoading, setQuotaLoading] = useState(true);
    const [quotaError, setQuotaError] = useState<string | null>(null);

    const refreshQuota = useCallback(async () => {
        if (!account?.profile.username) {
            setQuota(null);
            setQuotaLoading(false);
            return;
        }
        setQuotaLoading(true);
        setQuotaError(null);
        try {
            const headers = new Headers();
            const workspaceId = getActiveWorkspaceIdForRequest();
            if (workspaceId) headers.set("X-Workspace-ID", workspaceId);
            const result = await requestAccountApi<QuotaSummary>("/accounts/api/me/quota/", { headers });
            setQuota(result);
        } catch (error) {
            setQuota(null);
            setQuotaError(error instanceof Error ? error.message : "Could not load storage usage.");
        } finally {
            setQuotaLoading(false);
        }
    }, [account?.profile.username]);

    useEffect(() => {
        const timer = window.setTimeout(() => { void refreshQuota(); }, 0);
        const onQuotaInvalidated = () => { void refreshQuota(); };
        window.addEventListener(WORKSPACE_CHANGED_EVENT, onQuotaInvalidated);
        window.addEventListener(FOLDER_TREE_REFRESH_EVENT, onQuotaInvalidated);
        window.addEventListener(DRIVE_UPLOAD_COMPLETED_EVENT, onQuotaInvalidated);
        return () => {
            window.clearTimeout(timer);
            window.removeEventListener(WORKSPACE_CHANGED_EVENT, onQuotaInvalidated);
            window.removeEventListener(FOLDER_TREE_REFRESH_EVENT, onQuotaInvalidated);
            window.removeEventListener(DRIVE_UPLOAD_COMPLETED_EVENT, onQuotaInvalidated);
        };
    }, [refreshQuota]);

    const refreshFolderTree = useCallback(async () => {
        try {
            const result = await requestAccountApi<{ items: FolderTreeNode[] }>("/drive/api/folder-tree/");
            setFolderTree(result.items ?? []);
        } catch {
            // Keep navigation usable while storage/API services are unavailable.
        }
    }, []);

    useEffect(() => {
        const onFolderTreeRefresh = () => { void refreshFolderTree(); };
        // Defer the initial request so the effect itself does not synchronously
        // trigger state updates; the API response updates state asynchronously.
        const initialRefresh = window.setTimeout(() => {
            void refreshFolderTree();
        }, 0);
        window.addEventListener(FOLDER_TREE_REFRESH_EVENT, onFolderTreeRefresh);
        window.addEventListener(WORKSPACE_CHANGED_EVENT, onFolderTreeRefresh);
        return () => {
            window.clearTimeout(initialRefresh);
            window.removeEventListener(FOLDER_TREE_REFRESH_EVENT, onFolderTreeRefresh);
            window.removeEventListener(WORKSPACE_CHANGED_EVENT, onFolderTreeRefresh);
        };
    }, [refreshFolderTree]);

    const toggleFolder = useCallback((folderId: number) => {
        setExpandedFolders((current) => {
            const next = new Set(current);
            if (next.has(folderId)) next.delete(folderId);
            else next.add(folderId);
            return next;
        });
    }, []);

    const renderFolderNode = (node: FolderTreeNode, depth = 0) => {
        const href = `/drive/folders/${node.id}`;
        const active = pathname === href || pathname.startsWith(`${href}/`);
        const expanded = expandedFolders.has(node.id);
        return (
            <div key={node.id}>
                <div className={`group flex h-9 items-center rounded-lg pr-1 transition-colors ${active ? "bg-brand-soft text-brand-contrast" : "text-muted hover:bg-background hover:text-foreground"}`} style={{ paddingLeft: `${8 + depth * 12}px` }}>
                    <button
                        type="button"
                        aria-label={expanded ? `Collapse ${node.name}` : `Expand ${node.name}`}
                        aria-expanded={expanded}
                        onClick={() => toggleFolder(node.id)}
                        className="flex h-7 w-6 shrink-0 items-center justify-center rounded-md hover:bg-surface"
                    >
                        {node.children.length > 0
                            ? expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
                            : <span className="w-3" />}
                    </button>
                    <Link
                        href={href}
                        onClick={() => {
                            const path = collectAncestorIds(folderTree, node.id);
                            if (path) {
                                setExpandedFolders((current) => new Set([...current, ...path]));
                            }
                            onNavigate();
                        }}
                        aria-current={active ? "page" : undefined}
                        title={node.name}
                        className="flex min-w-0 flex-1 items-center gap-2 py-1 text-[12px] font-medium"
                    >
                        <Folder size={14} className="shrink-0" />
                        <span className="truncate">{node.name}</span>
                    </Link>
                </div>
                {expanded && node.children.length > 0 && (
                    <div>{node.children.map((child) => renderFolderNode(child, depth + 1))}</div>
                )}
            </div>
        );
    };

    return (
        <aside ref={navigationRef} id="drive-navigation" className={`fixed inset-y-0 left-0 z-50 flex h-screen w-57.5 shrink-0 flex-col border-r border-border bg-surface transition-transform duration-(--motion-normal) lg:static lg:z-auto lg:translate-x-0 ${
            mobileOpen ? "visible translate-x-0" : "invisible -translate-x-full lg:visible"
        }`}>
            <div className="flex h-18 shrink-0 items-center justify-between px-4">
                <Link href="/drive" onClick={() => { clearActiveWorkspaceSelection(); onNavigate(); }} className="flex min-w-0 items-center">
                    <BrandLogo />
                </Link>
                <button
                    type="button"
                    aria-label="Close navigation"
                    onClick={onNavigate}
                    className="flex h-9 w-9 items-center justify-center rounded-lg text-muted transition-colors duration-(--motion-fast) hover:bg-brand-soft hover:text-brand-contrast lg:hidden"
                >
                    <X size={18} />
                </button>
            </div>

            <WorkspaceSwitcher />

            <div className="px-3 pb-4"><DriveNewMenu /></div>

            <nav className="flex-1 overflow-y-auto px-2 pb-3">
                <div className="space-y-1">
                    {navigationItems.map((item) => {
                        const Icon = item.icon;
                        const active = item.href === "/drive"
                            ? pathname === "/drive" || pathname.startsWith("/drive/folders/")
                            : pathname === item.href || pathname.startsWith(`${item.href}/`);

                        if (item.href === "/drive") {
                            return (
                                <div key={item.href}>
                                    <div className={`flex h-10 items-center rounded-xl text-[14px] transition-colors duration-(--motion-fast) ${active ? "bg-brand-soft font-semibold text-brand-contrast shadow-[inset_3px_0_0_var(--brand-primary-contrast)]" : "font-medium text-muted hover:bg-background hover:text-foreground"}`}>
                                        <Link href={item.href} onClick={() => { if (item.href === "/drive") clearActiveWorkspaceSelection(); onNavigate(); }} aria-current={active ? "page" : undefined} className="flex min-w-0 flex-1 items-center gap-3 px-3">
                                            <Icon size={17} strokeWidth={active ? 2 : 1.8} />
                                            <span>{item.label}</span>
                                        </Link>
                                        <button type="button" aria-label={myDriveExpanded ? "Collapse My Drive folders" : "Expand My Drive folders"} aria-expanded={myDriveExpanded} onClick={() => setMyDriveExpanded((current) => !current)} className="mr-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg hover:bg-surface">
                                            {myDriveExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                                        </button>
                                    </div>
                                    {myDriveExpanded && folderTree.length > 0 && (
                                        <div className="mt-1 space-y-0.5">{folderTree.map((node) => renderFolderNode(node))}</div>
                                    )}
                                </div>
                            );
                        }

                        return (
                            <Link key={item.href} href={item.href} onClick={onNavigate} aria-current={active ? "page" : undefined} className={[
                                "flex h-10 items-center gap-3 rounded-xl px-3 text-[14px] transition-colors duration-(--motion-fast)",
                                active ? "bg-brand-soft font-semibold text-brand-contrast shadow-[inset_3px_0_0_var(--brand-primary-contrast)]" : "font-medium text-muted hover:bg-background hover:text-foreground",
                            ].join(" ")}>
                                <Icon size={17} strokeWidth={active ? 2 : 1.8} />
                                <span>{item.label}</span>
                            </Link>
                        );
                    })}
                    {canManageOrganization && (
                        <Link
                            href="/organization/admin"
                            onClick={onNavigate}
                            aria-current={pathname === "/organization/admin" || pathname.startsWith("/organization/admin/") ? "page" : undefined}
                            className={[
                                "mt-2 flex h-10 items-center gap-3 rounded-xl px-3 text-[14px] transition-colors duration-(--motion-fast)",
                                pathname === "/organization/admin" || pathname.startsWith("/organization/admin/")
                                    ? "bg-brand-soft font-semibold text-brand-contrast shadow-[inset_3px_0_0_var(--brand-primary-contrast)]"
                                    : "font-medium text-muted hover:bg-background hover:text-foreground",
                            ].join(" ")}
                        >
                            <Building2 size={17} />
                            <span>Organization admin</span>
                        </Link>
                    )}
                </div>
            </nav>

            <div className="m-4 rounded-[20px] border border-border bg-surface px-4 py-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="text-[12px] font-medium text-muted">Storage</span>
                    <span className="text-[11px] font-semibold text-foreground">
                        {quotaLoading ? "Loading…" : quota?.configured ? (quota.limitBytes == null ? "No limit" : `${quota.percentUsed ?? 0}%`) : "Quota"}
                    </span>
                </div>
                {quotaLoading ? (
                    <div className="h-1.5 overflow-hidden rounded-full bg-background"><div className="h-full w-1/3 animate-pulse rounded-full bg-brand" /></div>
                ) : quota?.configured ? (
                    <>
                        <div className="h-1.5 overflow-hidden rounded-full bg-background" role="progressbar" aria-label="Storage quota used" aria-valuemin={0} aria-valuemax={100} aria-valuenow={quota.percentUsed ?? 0}>
                            <div className={`h-full rounded-full ${(quota.percentUsed ?? 0) >= 95 ? "bg-danger" : "bg-brand-contrast"}`} style={{ width: `${Math.min(100, Math.max(0, quota.percentUsed ?? 0))}%` }} />
                        </div>
                        <p className="mt-2 text-[11px] text-muted">
                            {formatStorageBytes(quota.usedBytes)} used{quota.limitBytes == null ? "" : ` of ${formatStorageBytes(quota.limitBytes)}`}
                        </p>
                        {quota.reservedBytes ? <p className="mt-1 text-[10px] text-muted">{formatStorageBytes(quota.reservedBytes)} reserved for uploads</p> : null}
                        {quota.organizationCap ? (
                            <p className="mt-1 text-[10px] leading-4 text-muted">
                                Organization cap: {formatStorageBytes(quota.organizationCap.usedBytes)} used
                                {quota.organizationCap.limitBytes == null ? " · no limit" : ` of ${formatStorageBytes(quota.organizationCap.limitBytes)}`}
                                {quota.organizationCap.reservedBytes ? ` · ${formatStorageBytes(quota.organizationCap.reservedBytes)} reserved` : ""}
                            </p>
                        ) : null}
                    </>
                ) : (
                    <p className="mt-2 text-[11px] leading-4 text-muted">{quota?.message ?? quotaError ?? "Storage quota is not configured."}</p>
                )}
            </div>
        </aside>
    );
}
