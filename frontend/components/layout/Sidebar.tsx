"use client";

import type { Ref } from "react";
import {
    Clock3,
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

type SidebarProps = {
    mobileOpen: boolean;
    onNavigate: () => void;
    navigationRef: Ref<HTMLElement>;
};

const navigationItems = [
    {
        label: "My Drive",
        href: "/drive",
        icon: HardDrive,
    },
    {
        label: "Shared with me",
        href: "/drive/shared",
        icon: Share2,
    },
    {
        label: "Recent",
        href: "/drive/recent",
        icon: Clock3,
    },
    {
        label: "Starred",
        href: "/drive/starred",
        icon: Star,
    },
    {
        label: "Trash",
        href: "/drive/trash",
        icon: Trash2,
    },
];

export default function Sidebar({
    mobileOpen,
    onNavigate,
    navigationRef,
}: SidebarProps) {
    const pathname = usePathname();

    return (
        <aside ref={navigationRef} id="drive-navigation" className={`fixed inset-y-0 left-0 z-50 flex h-screen w-[230px] shrink-0 flex-col border-r border-border bg-surface transition-transform duration-[var(--motion-normal)] lg:static lg:z-auto lg:translate-x-0 ${
            mobileOpen ? "visible translate-x-0" : "invisible -translate-x-full lg:visible"
        }`}>
            <div className="flex h-[72px] shrink-0 items-center justify-between px-4">
                <Link href="/drive" onClick={onNavigate} className="flex min-w-0 items-center">
                    <BrandLogo />
                </Link>
                <button
                    type="button"
                    aria-label="Close navigation"
                    onClick={onNavigate}
                    className="flex h-9 w-9 items-center justify-center rounded-lg text-muted transition-colors duration-[var(--motion-fast)] hover:bg-brand-soft hover:text-brand-contrast lg:hidden"
                >
                    <X size={18} />
                </button>
            </div>

            <div className="px-3 pb-5">
                <DriveNewMenu />
            </div>

            <nav className="flex-1 px-2">
                <div className="space-y-1">
                    {navigationItems.map((item) => {
                        const Icon = item.icon;

                        const active =
                            item.href === "/drive"
                                ? pathname === "/drive"
                                : pathname === item.href || pathname.startsWith(`${item.href}/`);

                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                onClick={onNavigate}
                                aria-current={active ? "page" : undefined}
                                className={[
                                    "flex h-10 items-center gap-3 rounded-xl px-3 text-[14px] transition-colors duration-[var(--motion-fast)]",
                                    active
                                        ? "bg-brand-soft font-semibold text-brand-contrast shadow-[inset_3px_0_0_var(--brand-primary-contrast)]"
                                        : "font-medium text-muted hover:bg-background hover:text-foreground",
                                ].join(" ")}
                            >
                                <Icon size={17} strokeWidth={active ? 2 : 1.8} />
                                <span>{item.label}</span>
                            </Link>
                        );
                    })}
                </div>
            </nav>

            <div className="m-4 rounded-[20px] border border-border bg-surface px-4 py-4">
                <div className="mb-2 flex items-center justify-between">
                    <span className="text-[12px] font-medium text-muted">
                        Storage
                    </span>

                    <span className="text-[12px] font-medium text-foreground">
                        Not connected
                    </span>
                </div>

                <p className="mt-2 text-[11px] text-muted">
                    Usage details will appear when storage is connected.
                </p>
            </div>
        </aside>
    );
}