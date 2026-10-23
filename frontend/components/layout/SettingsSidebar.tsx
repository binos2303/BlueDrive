"use client";

import Link from "next/link";
import type { RefObject } from "react";
import { ArrowLeft, Plug, Settings2, ShieldCheck } from "lucide-react";

const items = [
  { id: "general", label: "General Settings", icon: Settings2 },
  { id: "privacy", label: "Privacy", icon: ShieldCheck },
  { id: "connections", label: "Connected Apps", icon: Plug },
];

export default function SettingsSidebar({ navigationRef, mobileOpen, active, onChange, onNavigate }: {
  navigationRef: RefObject<HTMLElement | null>;
  mobileOpen: boolean;
  active: string;
  onChange: (section: string) => void;
  onNavigate: () => void;
}) {
  return (
    <aside ref={navigationRef} aria-label="Settings navigation"
      className={`fixed inset-y-0 left-0 z-50 flex w-[250px] flex-col border-r border-border bg-surface p-4 transition-transform lg:static lg:z-auto lg:translate-x-0 ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}>
      <Link href="/drive" onClick={onNavigate} className="mb-8 flex items-center gap-3 rounded-xl px-2 py-2 text-sm font-semibold text-foreground hover:bg-background">
        <ArrowLeft size={18} /> Settings
      </Link>
      <nav className="space-y-1">
        {items.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" aria-current={active === id ? "page" : undefined}
            onClick={() => { onChange(id); onNavigate(); }}
            className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[13px] font-medium transition-colors ${active === id ? "bg-brand-soft text-brand-contrast" : "text-muted hover:bg-background hover:text-foreground"}`}>
            <Icon size={17} /> {label}
          </button>
        ))}
      </nav>
    </aside>
  );
}
