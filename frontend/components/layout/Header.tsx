"use client";

import type { Ref } from "react";
import {
    Bell,
    Menu,
    Search,
    Sparkles,
} from "lucide-react";
import { useRouter } from "next/navigation";
import ContextMenu, { type ContextMenuAction } from "@/components/ui/ContextMenu";
import Toast from "@/components/ui/Toast";
import { useAccount } from "@/components/account/AccountProvider";

export default function Header({
    mobileOpen,
    onMenuClick,
    menuButtonRef,
}: {
    mobileOpen: boolean;
    onMenuClick: () => void;
    menuButtonRef: Ref<HTMLButtonElement>;
}) {
    const router = useRouter();
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
            label: "Profile",
            onSelect: () => router.push("/account/profile"),
        },
        {
            label: "Settings",
            onSelect: () => router.push("/account/settings"),
        },
        {
            label: "Support",
            onSelect: () => router.push("/account/support"),
        },
    ];
    if (account?.account.type === "individual" && account.account.upgradeEligible === true) {
        accountActions.push({
            label: "Upgrade plan",
            onSelect: () => router.push("/account/upgrade"),
        });
    }
    accountActions.push({
        label: "Sign out",
        onSelect: () => {
            void signOut().catch(() => undefined);
        },
    });

    return (
        <header className="flex h-[72px] shrink-0 items-center gap-2 border-b border-border bg-surface/90 px-3 backdrop-blur-sm sm:gap-3 sm:px-6">
            <button
                ref={menuButtonRef}
                type="button"
                aria-label="Open navigation"
                aria-controls="drive-navigation"
                aria-expanded={mobileOpen}
                onClick={onMenuClick}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-muted transition-colors duration-[var(--motion-fast)] hover:bg-brand-soft hover:text-brand-contrast lg:hidden"
            >
                <Menu size={20} />
            </button>

            <div className="relative min-w-0 w-full max-w-[420px] flex-1">
                <Search
                    size={16}
                    strokeWidth={1.8}
                    className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted"
                />

                <input
                    type="search"
                    disabled
                    aria-label="Search files and folders — not connected yet"
                    placeholder="Search files and folders · not connected"
                    title="Search is not connected yet"
                    className="h-10 w-full rounded-xl border border-border bg-background pl-10 pr-3 text-[13px] text-foreground outline-none transition placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand/10 disabled:cursor-not-allowed disabled:opacity-70"
                />
            </div>

            <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:gap-3">
                {account?.account.type === "individual" && account.account.upgradeEligible === true && (
                    <button
                        type="button"
                        onClick={() => router.push("/account/upgrade")}
                        className="hidden h-9 items-center gap-2 rounded-lg bg-brand-contrast px-3 text-[12px] font-semibold text-white transition-colors hover:bg-brand-hover sm:flex"
                    >
                        <Sparkles size={14} strokeWidth={2} />
                        Upgrade plan
                    </button>
                )}

                <button
                    type="button"
                    disabled
                    aria-label="Notifications — not connected yet"
                    title="Notifications are not connected yet"
                    className="flex h-9 w-9 items-center justify-center rounded-full text-muted opacity-60"
                >
                    <Bell size={17} strokeWidth={1.8} />
                </button>

                <ContextMenu
                    label={accountState.status === "loading" ? "Account actions" : accountState.status === "error" ? "Account actions · account data unavailable" : `Account actions for ${profileLabel}`}
                    trigger={<><div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand">{initials}</div><span className="hidden max-w-32 truncate text-[13px] font-semibold text-foreground xl:block">{profileLabel}</span></>}
                    actions={accountActions}
                    triggerClassName="flex min-h-10 items-center gap-2 rounded-lg p-1 text-left transition-colors hover:bg-background"
                />
            </div>
            {actionError && (
                <div className="fixed bottom-4 left-4 z-[80] w-[min(24rem,calc(100vw-2rem))]">
                    <Toast title="Account action failed" variant="error" onDismiss={clearActionError}>
                        {actionError}
                    </Toast>
                </div>
            )}
        </header>
    );
}