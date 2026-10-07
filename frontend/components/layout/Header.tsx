"use client";

import {
    Bell,
    Search,
    Sparkles,
} from "lucide-react";

export default function Header() {
    return (
        <header className="flex h-[86px] shrink-0 items-center  px-8">
            {/* Search */}
            <div className="relative w-full max-w-[500px]">
                <Search
                    size={19}
                    strokeWidth={1.8}
                    className="absolute left-4 top-1/2 -translate-y-1/2 text-[#71809A]"
                />

                <input
                    type="search"
                    placeholder="Search files and folders..."
                    className="h-12 w-full rounded-[14px] border border-[#AEBBD3] bg-white pl-11 pr-4 text-[14px] text-[#121523] outline-none shadow-[0_3px_8px_rgba(18,21,35,0.08)] transition placeholder:text-[#8FA0BB] focus:border-[#7188F9] focus:ring-2 focus:ring-[#7188F9]/10"
                />
            </div>

            {/* Right side */}
            <div className="ml-auto flex items-center gap-5">
                {/* Upgrade */}
                <button
                    type="button"
                    className="flex h-12 items-center gap-2 rounded-[13px] bg-[#7188F9] px-5 text-[14px] font-semibold text-white transition hover:bg-[#5F75E8]"
                >
                    <Sparkles
                        size={17}
                        strokeWidth={2}
                    />
                    Upgrade
                </button>

                {/* Notification */}
                <button
                    type="button"
                    aria-label="Notifications"
                    className="flex h-10 w-10 items-center justify-center rounded-full text-[#71809A] transition hover:bg-[#EEF1FF] hover:text-[#7188F9]"
                >
                    <Bell
                        size={19}
                        strokeWidth={1.8}
                    />
                </button>

                {/* User */}
                <button
                    type="button"
                    className="flex items-center gap-2.5 rounded-xl p-1.5 transition hover:bg-[#EEF1FF]"
                >
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#7188F9] text-sm font-semibold text-white">
                        U
                    </div>

                    <span className="hidden text-[14px] font-semibold text-[#121523] xl:block">
                        User
                    </span>
                </button>
            </div>
        </header>
    );
}