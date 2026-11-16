"use client";

import type { Ref } from "react";
import {
    Menu,
    Search,
    Sparkles,
} from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { DRIVE_SEARCH_CHANGED_EVENT, WORKSPACE_CHANGED_EVENT } from "@/lib/workspace-context";
import { useEffect, useState, type FormEvent } from "react";
import ContextMenu, { type ContextMenuAction } from "@/components/ui/ContextMenu";
import Toast from "@/components/ui/Toast";
import { useAccount } from "@/components/account/AccountProvider";
import WorkspaceSwitcher from "@/components/workspaces/WorkspaceSwitcher";
import type { OrganizationWorkspace } from "@/lib/workspace-service";
import useActiveWorkspaceId from "@/components/workspaces/useActiveWorkspaceId";
import { drivePath } from "@/lib/drive-paths";

export default function Header({
    mobileOpen,
    onMenuClick,
    menuButtonRef,
    onWorkspaceChange,
}: {
    mobileOpen: boolean;
    onMenuClick: () => void;
    menuButtonRef: Ref<HTMLButtonElement>;
    onWorkspaceChange: (workspace: OrganizationWorkspace | null) => void;
}) {
    const router = useRouter();
    const pathname = usePathname();
    const driveRoot = drivePath(useActiveWorkspaceId());
    const [searchText, setSearchText] = useState("");

    useEffect(() => {
        const syncSearchFromUrl = () => {
            const params = new URLSearchParams(window.location.search);
            setSearchText(params.get("q") ?? "");
        };
        syncSearchFromUrl();
        const clearSearchOnWorkspaceSwitch = () => setSearchText("");
        const syncSearchFromEvent = (event: Event) => {
            const query = (event as CustomEvent<{ query?: unknown }>).detail?.query;
            if (typeof query === "string") setSearchText(query);
        };
        window.addEventListener("popstate", syncSearchFromUrl);
        window.addEventListener(DRIVE_SEARCH_CHANGED_EVENT, syncSearchFromEvent);
        window.addEventListener(WORKSPACE_CHANGED_EVENT, clearSearchOnWorkspaceSwitch);
        return () => {
            window.removeEventListener("popstate", syncSearchFromUrl);
            window.removeEventListener(DRIVE_SEARCH_CHANGED_EVENT, syncSearchFromEvent);
            window.removeEventListener(WORKSPACE_CHANGED_EVENT, clearSearchOnWorkspaceSwitch);
        };
    }, [pathname]);

    function submitSearch(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const query = searchText.trim().slice(0, 255);
        setSearchText(query);
        router.push(query ? `${driveRoot}?q=${encodeURIComponent(query)}` : driveRoot);
        // If we are already on Drive, keep the mounted file browser in sync.
        // Other routes remount Drive and read the submitted query from the URL.
        if (pathname === driveRoot) {
            window.dispatchEvent(new CustomEvent(DRIVE_SEARCH_CHANGED_EVENT, { detail: { query } }));
        }
    }
    const {
        state: accountState,
        signOut,
        actionError,
        clearActionError,
    } = useAccount();
    const account = accountState.status === "loaded" ? accountState.account : null;
    const profileLabel = account?.profile.username || account?.profile.email || "Account";
    const initials = profileLabel.slice(0, 1).toUpperCase();
    const accountActions: ContextMenuAction[] = [
        {
            label: "Settings",
            onSelect: () => router.push("/account/settings"),
        },
    ];
    accountActions.push({
        label: "Sign out",
        onSelect: () => {
            void signOut().catch(() => undefined);
        },
    });

    return (
        <header className="grid shrink-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 border-b border-border bg-surface px-3 py-2 sm:gap-3 md:flex md:min-h-16 md:px-4 lg:px-5">
            <button
                ref={menuButtonRef}
                type="button"
                aria-label="Open navigation"
                aria-controls="drive-navigation"
                aria-expanded={mobileOpen}
                onClick={onMenuClick}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-muted transition-colors duration-(--motion-fast) hover:bg-brand-soft hover:text-brand-contrast lg:hidden"
            >
                <Menu size={20} />
            </button>

            <div className="min-w-0 md:w-48 md:shrink-0"><WorkspaceSwitcher onWorkspaceChange={onWorkspaceChange} /></div>

            <form onSubmit={submitSearch} role="search" className="relative col-span-full row-start-2 min-w-0 w-full flex-1 md:max-w-xl">
                <Search
                    size={16}
                    strokeWidth={1.8}
                    className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted"
                />
                <input
                    type="search"
                    value={searchText}
                    maxLength={255}
                    onChange={(event) => setSearchText(event.currentTarget.value)}
                    aria-label="Search files and folders"
                    placeholder="Search files and folders"
                    title="Search in the current Drive or workspace"
                    className="h-11 w-full rounded-xl border border-border bg-background pl-10 pr-3 text-sm text-foreground outline-none transition placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand/10"
                />
            </form>

            <div className="col-start-3 row-start-1 ml-auto flex shrink-0 items-center gap-2">
                {account?.account.type === "individual" && account.account.upgradeEligible === true && (
                    <button
                        type="button"
                        onClick={() => router.push("/account/upgrade")}
                        className="ui-control hidden min-h-10 items-center gap-2 rounded-lg bg-brand-contrast px-3 text-[13px] font-semibold text-on-accent transition-colors hover:bg-brand-hover 2xl:flex"
                    >
                        <Sparkles size={14} strokeWidth={2} />
                        Plan details
                    </button>
                )}

                <ContextMenu
                    label={accountState.status === "loading" ? "Account actions" : accountState.status === "error" ? "Account actions · account data unavailable" : `Account actions for ${profileLabel}`}
                    trigger={<><div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand-contrast">{initials}</div><span className="hidden max-w-32 truncate text-[13px] font-semibold text-foreground xl:block">{profileLabel}</span></>}
                    actions={accountActions}
                    triggerClassName="flex min-h-10 items-center gap-2 rounded-lg p-1 text-left transition-colors hover:bg-background"
                />
            </div>
            {actionError && (
                <div className="fixed bottom-4 left-4 z-80 w-[min(24rem,calc(100vw-2rem))]">
                    <Toast title="Account action failed" variant="error" onDismiss={clearActionError}>
                        {actionError}
                    </Toast>
                </div>
            )}
        </header>
    );
}
