"use client";

import Link from "next/link";
import type { RefObject } from "react";
import { ArrowLeft, Plug, Settings2, Shield, ShieldCheck, X } from "lucide-react";
import { BrandLogo } from "@/components/ui/BrandLogo";
import DriveNewMenu from "@/components/drive/DriveNewMenu";
import { clearActiveWorkspaceSelection } from "@/lib/workspace-context";
import useActiveWorkspaceId from "@/components/workspaces/useActiveWorkspaceId";
import { drivePath } from "@/lib/drive-paths";

const items = [
  { id: "general", label: "General Settings", icon: Settings2 },
  { id: "security", label: "Profile & Security", icon: Shield },
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
  const driveRoot = drivePath(useActiveWorkspaceId());
  return (
    <aside ref={navigationRef} id="drive-navigation" aria-label="Settings navigation"
      className={`fixed inset-y-0 left-0 z-50 flex h-dvh w-64 max-w-[calc(100vw-3rem)] shrink-0 flex-col border-r border-border bg-surface transition-transform duration-(--motion-normal) lg:static lg:z-auto lg:translate-x-0 ${mobileOpen ? "visible translate-x-0" : "invisible -translate-x-full lg:visible"}`}>
      <div className="flex h-16 shrink-0 items-center justify-between px-4">
        <Link href="/drive" onClick={() => { clearActiveWorkspaceSelection(); onNavigate(); }} aria-label="BlueDrive My Drive"><BrandLogo /></Link>
        <button type="button" aria-label="Close navigation" onClick={onNavigate} className="ui-control flex h-10 w-10 items-center justify-center rounded-lg text-muted hover:bg-background lg:hidden"><X size={18} /></button>
      </div>
      <div className="shrink-0 px-3 pb-3"><DriveNewMenu onAction={onNavigate} /></div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        <Link href={driveRoot} onClick={onNavigate} className="mb-3 flex min-h-11 items-center gap-3 rounded-xl border-b border-border px-3 py-3 text-sm font-medium text-muted hover:text-foreground">
          <ArrowLeft size={18} /> Back to Drive
        </Link>
      <nav className="space-y-1" aria-label="Settings sections">
        {items.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" aria-current={active === id ? "page" : undefined} aria-controls="account-settings-panel"
            onClick={() => { onChange(id); onNavigate(); }}
            className={`flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium transition-colors ${active === id ? "bg-brand-soft text-brand-contrast" : "text-muted hover:bg-background hover:text-foreground"}`}>
            <Icon size={17} /> {label}
          </button>
        ))}
      </nav>
      </div>
    </aside>
  );
}
