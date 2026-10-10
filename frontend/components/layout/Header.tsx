"use client";

import {
    Bell,
    Search,
    Sparkles,
} from "lucide-react";

export default function Header() {
    return (
        <header className="flex h-[72px] shrink-0 items-center border-b border-border bg-surface/90 px-6 backdrop-blur-sm">
            <div className="relative w-full max-w-[420px]">
                <Search
                    size={16}
                    strokeWidth={1.8}
                    className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted"
                />

                <input
                    type="search"
                    placeholder="Search files and folders..."
                    className="h-10 w-full rounded-xl border border-border bg-background pl-10 pr-3 text-[13px] text-foreground outline-none transition placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand/10"
                />
            </div>

            <div className="ml-auto flex items-center gap-3">
                <button
                    type="button"
                    className="flex h-9 items-center gap-2 rounded-lg bg-brand px-3 text-[12px] font-semibold text-white transition hover:bg-brand-hover"
                >
                    <Sparkles size={14} strokeWidth={2} />
                    Upgrade
                </button>

                <button
                    type="button"
                    aria-label="Notifications"
                    className="flex h-9 w-9 items-center justify-center rounded-full text-muted transition hover:bg-brand-soft hover:text-brand"
                >
                    <Bell size={17} strokeWidth={1.8} />
                </button>

                <button
                    type="button"
                    className="flex items-center gap-2 rounded-lg p-1 transition hover:bg-brand-soft"
                >
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand">
                        U
                    </div>

                    <span className="hidden text-[13px] font-semibold text-foreground xl:block">
                        User
                    </span>
                </button>
            </div>
        </header>
    );
}