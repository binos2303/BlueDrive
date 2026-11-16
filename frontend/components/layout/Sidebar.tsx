"use client";

import { useCallback, useEffect, useRef, useState, type Ref } from "react";
import {
    Clock3,
    Building2,
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
import WorkspaceSidebar from "./WorkspaceSidebar";
import DriveFolderNavigation from "./DriveFolderNavigation";
import useActiveWorkspaceId from "@/components/workspaces/useActiveWorkspaceId";
import type { OrganizationWorkspace } from "@/lib/workspace-service";
import { useAccount } from "@/components/account/AccountProvider";
import { DRIVE_UPLOAD_COMPLETED_EVENT, FOLDER_TREE_REFRESH_EVENT, WORKSPACE_CHANGED_EVENT } from "@/lib/workspace-context";
import { requestAccountApi } from "@/lib/account-service";
import { clearActiveWorkspaceSelection, getActiveWorkspaceIdForRequest } from "@/lib/workspace-context";
import { driveFolderIdFromPathname } from "@/lib/drive-paths";
import StorageNavigationLink from "@/components/storage/StorageNavigationLink";

type SidebarProps = {
    workspace: OrganizationWorkspace | null;
    sharedFolderId: number | null;
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

export default function Sidebar({ mobileOpen, onNavigate, navigationRef, workspace, sharedFolderId }: SidebarProps) {
    const pathname = usePathname();
    const activeWorkspaceId = useActiveWorkspaceId();
    const inSharedFolder = sharedFolderId !== null && sharedFolderId === driveFolderIdFromPathname(pathname) && !activeWorkspaceId;
    const { state: accountState } = useAccount();
    const account = accountState.status === "loaded" ? accountState.account : null;
    const tenant = account?.account.tenant ?? null;
    const canManageOrganization = Boolean(
        account?.account.type === "business" && tenant && ["owner", "admin"].includes(tenant.role),
    );
    const [quota, setQuota] = useState<QuotaSummary | null>(null);
    const [quotaLoading, setQuotaLoading] = useState(true);
    const [quotaError, setQuotaError] = useState<string | null>(null);
    const quotaRequestId = useRef(0);

    const refreshQuota = useCallback(async () => {
        const requestId = ++quotaRequestId.current;
        const selectedWorkspaceId = getActiveWorkspaceIdForRequest();
        if (!account?.profile.username) {
            setQuota(null);
            setQuotaLoading(false);
            return;
        }
        setQuotaLoading(true);
        setQuotaError(null);
        try {
            const headers = new Headers();
            if (selectedWorkspaceId) headers.set("X-Workspace-ID", selectedWorkspaceId);
            const result = await requestAccountApi<QuotaSummary>("/accounts/api/me/quota/", { headers });
            if (requestId !== quotaRequestId.current || selectedWorkspaceId !== getActiveWorkspaceIdForRequest()) return;
            setQuota(result);
        } catch (error) {
            if (requestId !== quotaRequestId.current || selectedWorkspaceId !== getActiveWorkspaceIdForRequest()) return;
            setQuota(null);
            setQuotaError(error instanceof Error ? error.message : "Could not load storage usage.");
        } finally {
            if (requestId === quotaRequestId.current) setQuotaLoading(false);
        }
    }, [account?.profile.username]);

    useEffect(() => {
        const timer = window.setTimeout(() => { void refreshQuota(); }, 0);
        const onQuotaInvalidated = () => { void refreshQuota(); };
        window.addEventListener(WORKSPACE_CHANGED_EVENT, onQuotaInvalidated);
        window.addEventListener(FOLDER_TREE_REFRESH_EVENT, onQuotaInvalidated);
        window.addEventListener(DRIVE_UPLOAD_COMPLETED_EVENT, onQuotaInvalidated);
        return () => {
            quotaRequestId.current += 1;
            window.clearTimeout(timer);
            window.removeEventListener(WORKSPACE_CHANGED_EVENT, onQuotaInvalidated);
            window.removeEventListener(FOLDER_TREE_REFRESH_EVENT, onQuotaInvalidated);
            window.removeEventListener(DRIVE_UPLOAD_COMPLETED_EVENT, onQuotaInvalidated);
        };
    }, [refreshQuota, activeWorkspaceId]);

    return (
        <aside ref={navigationRef} id="drive-navigation" className={`fixed inset-y-0 left-0 z-50 flex h-dvh w-64 max-w-[calc(100vw-3rem)] shrink-0 flex-col border-r border-border bg-surface transition-transform duration-(--motion-normal) lg:static lg:z-auto lg:translate-x-0 ${
            mobileOpen ? "visible translate-x-0" : "invisible -translate-x-full lg:visible"
        }`}>
            <div className="flex h-16 shrink-0 items-center justify-between px-4">
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

            <div className="shrink-0 px-3 pb-3"><DriveNewMenu onAction={onNavigate} /></div>
            <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
              {activeWorkspaceId ? <WorkspaceSidebar workspaceId={activeWorkspaceId} workspace={workspace?.id === activeWorkspaceId ? workspace : null} pathname={pathname} onNavigate={onNavigate} /> : <nav aria-label="Drive navigation">
                <div className="space-y-1">
                    {navigationItems.map((item) => {
                        const Icon = item.icon;
                        const active = item.href === "/drive"
                            ? pathname === "/drive" || pathname.startsWith("/drive/folders/")
                            : pathname === item.href || pathname.startsWith(`${item.href}/`);

                        if (item.href === "/drive") {
                            return <DriveFolderNavigation key={account?.profile.username ?? "personal"} label={item.label} icon={Icon} workspaceId={null} pathname={pathname} activeOverride={inSharedFolder ? false : undefined} onNavigate={onNavigate} />;
                        }
                        return (
                            <Link key={item.href} href={item.href} onClick={onNavigate} aria-current={active || (item.href === "/drive/shared" && inSharedFolder) ? "page" : undefined} className={[
                                "flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm transition-colors duration-(--motion-fast)",
                                active || (item.href === "/drive/shared" && inSharedFolder) ? "bg-brand-soft font-semibold text-brand-contrast" : "font-medium text-muted hover:bg-background hover:text-foreground",
                            ].join(" ")}>
                                <Icon size={17} strokeWidth={active ? 2 : 1.8} />
                                <span>{item.label}</span>
                            </Link>
                        );
                    })}
                    {account?.account.type === "business" && tenant && <StorageNavigationLink key={tenant.id} tenantId={tenant.id} onNavigate={onNavigate} />}
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
              </nav>}
            </div>

            <div className="mx-4 mb-4 shrink-0 border-t border-border px-1 pt-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="text-[12px] font-medium text-muted">Storage</span>
                    <span className="text-xs font-semibold text-foreground">
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
                        <p className="mt-2 text-xs text-muted">
                            {formatStorageBytes(quota.usedBytes)} used{quota.limitBytes == null ? "" : ` of ${formatStorageBytes(quota.limitBytes)}`}
                        </p>
                        {quota.reservedBytes ? <p className="mt-1 text-xs text-muted">{formatStorageBytes(quota.reservedBytes)} reserved for uploads</p> : null}
                        {quota.organizationCap ? (
                            <p className="mt-1 text-xs leading-4 text-muted">
                                Organization cap: {formatStorageBytes(quota.organizationCap.usedBytes)} used
                                {quota.organizationCap.limitBytes == null ? " · no limit" : ` of ${formatStorageBytes(quota.organizationCap.limitBytes)}`}
                                {quota.organizationCap.reservedBytes ? ` · ${formatStorageBytes(quota.organizationCap.reservedBytes)} reserved` : ""}
                            </p>
                        ) : null}
                    </>
                ) : (
                    <p className="mt-2 text-xs leading-4 text-muted">{quota?.message ?? quotaError ?? "Storage quota is not configured."}</p>
                )}
            </div>
        </aside>
    );
}
