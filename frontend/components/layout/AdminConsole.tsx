"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity, Bell, Database, Gauge, UsersRound,
  LayoutDashboard, Menu, Search, ShieldCheck, Users,
  Server, HardDrive, Building2, History, ScrollText, Archive, RotateCcw, ClipboardList, SlidersHorizontal, X,
} from "lucide-react";
import { useState } from "react";
import { BrandLogo } from "@/components/ui/BrandLogo";

const groups = [
  {
    label: "Admin",
    items: [{ label: "Dashboard", href: "/admin", icon: LayoutDashboard }],
  },
  {
    label: "User Management",
    items: [
      { label: "User Directory", href: "/admin/users", icon: Users },
      { label: "Roles & Permissions", href: "/admin/permissions", icon: ShieldCheck },
      { label: "Team Management", href: "/admin/teams", icon: Building2 },
      { label: "User Audit History", href: "/admin/users/audit", icon: History },
    ],
  },
  {
    label: "Infrastructure",
    items: [
      { label: "Overview", href: "/admin/infrastructure", icon: Gauge },
      { label: "Servers", href: "/admin/infrastructure/servers", icon: Server },
      { label: "Storage & Disks", href: "/admin/infrastructure/storage", icon: HardDrive },
      { label: "Database", href: "/admin/infrastructure/database", icon: Database },
      { label: "MinIO", href: "/admin/infrastructure/minio", icon: Database },
      { label: "Alerts & Monitoring", href: "/admin/infrastructure/alerts", icon: Activity },
      { label: "Quota Management", href: "/admin/infrastructure/quotas", icon: UsersRound },
    ],
  },
  {
    label: "Activity & Audit",
    items: [
      { label: "User Activity", href: "/admin/activity", icon: Activity },
      { label: "System Audit Logs", href: "/admin/audit", icon: ScrollText },
    ],
  },
  {
    label: "Backup & Restore",
    items: [
      { label: "Backup Overview", href: "/admin/backups", icon: Database },
      { label: "Backup Jobs", href: "/admin/backups/jobs", icon: ClipboardList },
      { label: "Backup History", href: "/admin/backups/history", icon: Archive },
      { label: "Restore Center", href: "/admin/backups/restore", icon: RotateCcw },
      { label: "Backup Policies", href: "/admin/backups/policies", icon: SlidersHorizontal },
    ],
  },
];

export default function AdminConsole({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const selectedHref = groups
    .flatMap((group) => group.items)
    .filter(({ href }) => pathname === href || pathname.startsWith(`${href}/`))
    .sort((first, second) => second.href.length - first.href.length)[0]?.href;

  return (
    <div className="min-h-screen bg-background text-foreground">
      {mobileOpen && <button aria-label="Close navigation" onClick={() => setMobileOpen(false)} className="fixed inset-0 z-30 bg-slate-900/20 lg:hidden" />}

      <aside className={`fixed inset-y-0 left-0 z-40 flex w-[230px] flex-col border-r border-border bg-surface transition-transform duration-200 lg:translate-x-0 ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="flex h-[72px] items-center justify-between px-4">
          <Link href="/drive" className="flex items-center gap-3">
            <BrandLogo className="text-[18px]" />
          </Link>
          <button aria-label="Close navigation" onClick={() => setMobileOpen(false)} className="rounded-lg p-2 text-muted hover:bg-brand-soft lg:hidden"><X size={18} /></button>
        </div>

        <nav aria-label="Admin navigation" className="min-h-0 flex-1 overflow-y-auto px-2 pb-3 pt-1">
          {groups.map((group) => (
            <section key={group.label} className="mb-4">
              <h2 className="mb-1 px-3 pt-2 text-[10px] font-semibold tracking-[0.12em] text-muted/80">
                {group.label}
              </h2>
              <div className="space-y-0.5">
                {group.items.map(({ label, href, icon: Icon }) => {
                  const active = selectedHref === href;
                  return (
                    <Link
                      key={href}
                      href={href}
                      onClick={() => setMobileOpen(false)}
                      aria-current={active ? "page" : undefined}
                      className={`flex min-h-9 items-center gap-2.5 rounded-lg px-3 py-1.5 text-[12px] font-medium transition ${active ? "bg-brand-soft text-brand" : "text-muted hover:bg-background hover:text-foreground"}`}
                    >
                      <Icon size={16} strokeWidth={active ? 2.1 : 1.8} />
                      <span>{label}</span>
                    </Link>
                  );
                })}
              </div>
            </section>
          ))}
        </nav>

        <div className="border-t border-border p-3 text-xs text-muted/80">BlueDrive · Admin</div>
      </aside>

      <div className="min-h-screen lg:pl-[230px]">
        <header className="sticky top-0 z-20 flex h-[72px] items-center gap-3 border-b border-border bg-surface/90 px-4 backdrop-blur-sm sm:px-6">
          <button aria-label="Open navigation" onClick={() => setMobileOpen(true)} className="rounded-lg p-2 text-muted hover:bg-brand-soft lg:hidden"><Menu size={20} /></button>

          <div className="hidden w-full max-w-[320px] items-center gap-2 rounded-xl border border-border bg-background px-3 md:flex">
            <Search size={16} className="text-muted" />
            <input aria-label="Search admin" placeholder="Search..." className="h-9 min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted/80" />
          </div>

          <div className="ml-auto flex items-center gap-3">
            <button aria-label="Notifications" className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted transition hover:bg-brand-soft hover:text-brand">
              <Bell size={18} />
              <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-brand ring-2 ring-surface" />
            </button>

            <div className="hidden items-center gap-2 sm:flex">
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-soft text-sm font-semibold text-brand">AD</span>
              <div className="hidden xl:block">
                <p className="text-sm font-semibold text-foreground">Administrator</p>
              </div>
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1400px] p-4 sm:p-6">{children}</main>
      </div>
    </div>
  );
}
