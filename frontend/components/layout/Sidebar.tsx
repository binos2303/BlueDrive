"use client";

import {
    Clock3,
    HardDrive,
    Plus,
    Share2,
    Star,
    Trash2,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BrandLogo } from "@/components/ui/BrandLogo";

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

export default function Sidebar() {
    const pathname = usePathname();

    return (
        <aside className="flex h-screen w-[230px] shrink-0 flex-col border-r border-border bg-surface">
            <div className="flex h-[72px] shrink-0 items-center px-4">
                <Link href="/drive" className="flex min-w-0 items-center">
                    <BrandLogo />
                </Link>
            </div>

            <div className="px-3 pb-5">
                <button
                    type="button"
                    className="flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-brand text-sm font-semibold text-white transition hover:bg-brand-hover"
                >
                    <Plus size={16} strokeWidth={2} />
                    New
                </button>
            </div>

            <nav className="flex-1 px-2">
                <div className="space-y-1">
                    {navigationItems.map((item) => {
                        const Icon = item.icon;

                        const active =
                            item.href === "/drive"
                                ? pathname === "/drive"
                                : pathname.startsWith(item.href);

                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                className={[
                                    "flex h-10 items-center gap-3 rounded-xl px-3 text-[14px] transition",
                                    active
                                        ? "bg-brand-soft font-medium text-brand"
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
                        0 GB / 10 GB
                    </span>
                </div>

                <div className="h-[6px] overflow-hidden rounded-full bg-border">
                    <div className="h-full w-0 rounded-full bg-brand" />
                </div>
            </div>
        </aside>
    );
}