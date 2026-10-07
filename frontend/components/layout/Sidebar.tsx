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

const navigationItems = [
    {
        label: "My Drive",
        href: "/",
        icon: HardDrive,
    },
    {
        label: "Shared with me",
        href: "/shared",
        icon: Share2,
    },
    {
        label: "Recent",
        href: "/recent",
        icon: Clock3,
    },
    {
        label: "Starred",
        href: "/starred",
        icon: Star,
    },
    {
        label: "Trash",
        href: "/trash",
        icon: Trash2,
    },
];

export default function Sidebar() {
    const pathname = usePathname();

    return (
        <aside className="flex h-screen w-[278px] shrink-0 flex-col ">
            {/* Logo */}
            <div className="flex h-[86px] items-center px-7">
                <Link href="/" className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-[13px] bg-[#7188F9] text-sm font-semibold text-white">
                        B
                    </div>

                    <span className="text-[19px] font-semibold tracking-[-0.02em] text-[#121523]">
                        BlueDrive
                    </span>
                </Link>
            </div>

            {/* New */}
            <div className="px-4 pb-7">
                <button
                    type="button"
                    className="flex h-12 w-full items-center justify-center gap-2 rounded-[13px] bg-[#7188F9] text-sm font-semibold text-white transition hover:bg-[#5F75E8]"
                >
                    <Plus size={19} strokeWidth={2} />
                    New
                </button>
            </div>

            {/* Navigation */}
            <nav className="flex-1 px-3">
                <div className="space-y-1">
                    {navigationItems.map((item) => {
                        const Icon = item.icon;

                        const active =
                            item.href === "/"
                                ? pathname === "/"
                                : pathname.startsWith(item.href);

                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                className={[
                                    "flex h-11 items-center gap-3 rounded-[12px] px-4 text-[15px] transition",
                                    active
                                        ? "bg-[#EEF1FF] font-medium text-[#7188F9]"
                                        : "font-medium text-[#71809A] hover:bg-[#E9EDF4] hover:text-[#121523]",
                                ].join(" ")}
                            >
                                <Icon
                                    size={19}
                                    strokeWidth={active ? 2 : 1.8}
                                />

                                <span>{item.label}</span>
                            </Link>
                        );
                    })}
                </div>
            </nav>

            {/* Storage quota */}
            <div className="m-6 rounded-[28px] border border-[#E1E5ED] px-5 py-6">
                <div className="mb-2 flex items-center justify-between">
                    <span className="text-[13px] font-medium text-[#71809A]">
                        Storage
                    </span>

                    <span className="text-[13px] font-medium text-[#121523]">
                        0 GB / 10 GB
                    </span>
                </div>

                <div className="h-[6px] overflow-hidden rounded-full bg-[#E1E5ED]">
                    <div className="h-full w-0 rounded-full bg-[#7188F9]" />
                </div>
            </div>
        </aside>
    );
}