"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity, Building2, ChevronDown, ChevronRight, Database, FileText, HardDrive,
  LayoutDashboard, Menu, ShieldAlert, SunMoon, Users, Workflow, X,
} from "lucide-react";
import { BrandLogo } from "@/components/ui/BrandLogo";
import ContextMenu, { type ContextMenuAction } from "@/components/ui/ContextMenu";
import Toast from "@/components/ui/Toast";
import { useAccount } from "@/components/account/AccountProvider";
import { readThemePreference, resolveTheme, setThemePreference } from "@/lib/theme";

const groups = [
  {
    title: "Management", icon: Users,
    items: [
      { title: "Users", href: "/admin/users", icon: Users },
      { title: "Organizations", href: "/admin/organizations", icon: Building2 },
      { title: "Workspaces", href: "/admin/workspaces", icon: Workflow },
      { title: "Files", href: "/admin/files", icon: FileText },
    ],
  },
  {
    title: "Security", icon: ShieldAlert,
    items: [
      { title: "Security Alerts", href: "/admin/security/alerts", icon: ShieldAlert },
      { title: "User Activity", href: "/admin/activity", icon: Activity },
      { title: "Admin Audit Logs", href: "/admin/audit", icon: Activity },
    ],
  },
  {
    title: "Infrastructure", icon: Database,
    items: [
      { title: "System Health", href: "/admin/infrastructure", icon: Activity },
      { title: "Storage Topology", href: "/admin/infrastructure/topology", icon: HardDrive },
      { title: "Storage & Quotas", href: "/admin/infrastructure/quotas", icon: Database },
    ],
  },
] as const;

const apiOrigin = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
type Access = { allowed: boolean; username: string; email: string };

/** Choose the most specific match so System Health is not active on Storage Topology. */
function navItemActive(href: string, pathname: string) {
  if (pathname === href) return true;
  if (!pathname.startsWith(`${href}/`)) return false;
  return !groups.some(({ items }) => items.some(({ href: moreSpecific }) =>
    moreSpecific !== href && moreSpecific.startsWith(`${href}/`) &&
    (pathname === moreSpecific || pathname.startsWith(`${moreSpecific}/`)),
  ));
}

export default function AdminConsole({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { state, signOut, actionError, clearActionError } = useAccount();
  const [access, setAccess] = useState<Access | null>(null);
  const [error, setError] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const mobileNav = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const hadMobileNavOpen = useRef(false);

  useEffect(() => {
    if (state.status !== "loaded" || !state.account) return;
    const controller = new AbortController();
    fetch(`${apiOrigin}/accounts/api/admin/access/`, {
      credentials: "include", signal: controller.signal, cache: "no-store",
    }).then(async (response) => {
      if (!response.ok) throw new Error(response.status === 403
        ? "This account does not have platform administrator access."
        : `Unable to verify administrator access (HTTP ${response.status}).`);
      return response.json() as Promise<Access>;
    }).then((result) => {
      if (controller.signal.aborted) return;
      setAccess(result);
      setError("");
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Access check failed.");
    });
    return () => controller.abort();
  }, [state.status, state.account]);

  useEffect(() => {
    if (mobileOpen) mobileNav.current?.querySelector<HTMLAnchorElement>("a")?.focus();
    else if (hadMobileNavOpen.current) menuButton.current?.focus();
    hadMobileNavOpen.current = mobileOpen;
  }, [mobileOpen]);
  useEffect(() => {
    if (!mobileOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMobileOpen(false);
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [mobileOpen]);

  const activeGroup = groups.find(({ items }) => items.some(({ href }) => pathname === href || pathname.startsWith(`${href}/`)))?.title;
  const groupIsOpen = (title: string) => expanded[title] ?? title === activeGroup;
  const activeDashboard = pathname === "/admin";

  if (state.status === "error" || (state.status === "loaded" && !state.account)) {
    return <main className="flex min-h-screen items-center justify-center bg-background p-6"><div className="max-w-md text-center"><h1 className="text-xl font-semibold">Sign in required</h1><p className="mt-2 text-sm text-muted">{state.status === "error" ? state.error : "Sign in to continue."}</p><Link href="/login?next=%2Fadmin" className="mt-4 inline-block text-sm font-semibold text-brand">Sign in</Link></div></main>;
  }
  if (state.status !== "loaded" || (!access && !error)) {
    return <main className="flex min-h-screen items-center justify-center bg-background text-sm text-muted" role="status">Verifying administrator access…</main>;
  }
  if (error || !access?.allowed) {
    return <main className="flex min-h-screen items-center justify-center bg-background p-6"><div className="w-full max-w-md rounded-2xl border border-border bg-surface p-7"><h1 className="text-xl font-semibold">Administrator access required</h1><p role="alert" className="mt-3 text-sm text-muted">{error || "Access denied."}</p><Link href="/login?next=%2Fadmin" className="mt-5 inline-block text-sm font-semibold text-brand">Sign in as admin</Link></div></main>;
  }

  const initials = access.username.trim().slice(0, 2).toUpperCase() || "AD";
  const toggleTheme = () => setThemePreference(resolveTheme(readThemePreference()) === "dark" ? "light" : "dark");
  const accountActions: ContextMenuAction[] = [
    { label: "Manage accounts", onSelect: () => router.push("/admin/users") },
    { label: "Sign out", destructive: true, onSelect: () => { void signOut().catch(() => undefined); } },
  ];
  const navLinkClass = (selected: boolean) => [
    "flex h-10 items-center gap-3 rounded-xl px-3 text-[14px] transition-colors duration-(--motion-fast)",
    selected ? "bg-brand-soft font-semibold text-brand-contrast shadow-[inset_3px_0_0_var(--brand-primary-contrast)]" : "font-medium text-muted hover:bg-background hover:text-foreground",
  ].join(" ");

  return <div className="flex h-screen overflow-hidden bg-background text-foreground">
    {mobileOpen && <button type="button" aria-label="Close navigation" className="fixed inset-0 z-40 bg-foreground/35 lg:hidden" onClick={() => setMobileOpen(false)} />}
    <aside ref={mobileNav} id="admin-navigation" className={`fixed inset-y-0 left-0 z-50 flex h-screen w-57.5 shrink-0 flex-col border-r border-border bg-surface transition-transform duration-(--motion-normal) lg:static lg:z-auto lg:translate-x-0 ${mobileOpen ? "visible translate-x-0" : "invisible -translate-x-full lg:visible"}`}>
      <div className="flex h-18 shrink-0 items-center justify-between px-4">
        <Link href="/admin" onClick={() => setMobileOpen(false)} aria-label="BlueDrive Admin dashboard"><BrandLogo /></Link>
        <button type="button" aria-label="Close navigation" onClick={() => setMobileOpen(false)} className="flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-brand-soft hover:text-brand-contrast lg:hidden"><X size={18} /></button>
      </div>
      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-4" aria-label="Admin navigation">
        <Link href="/admin" aria-current={activeDashboard ? "page" : undefined} onClick={() => setMobileOpen(false)} className={navLinkClass(activeDashboard)}><LayoutDashboard size={17} /><span>Dashboard</span></Link>
        <div className="mt-4 space-y-2">
          {groups.map(({ title, icon: Icon, items }) => {
            const open = groupIsOpen(title);
            const selected = title === activeGroup;
            return <section key={title}>
              <button type="button" aria-expanded={open} aria-controls={`admin-nav-${title}`} onClick={() => setExpanded((current) => ({ ...current, [title]: !open }))} className={`flex h-10 w-full items-center gap-3 rounded-xl px-3 text-left text-[14px] font-medium transition-colors duration-(--motion-fast) hover:bg-background ${selected ? "text-brand-contrast" : "text-foreground"}`}>
                <Icon size={17} /><span className="min-w-0 flex-1">{title}</span>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
              </button>
              {open && <div id={`admin-nav-${title}`} className="ml-5 space-y-0.5 border-l border-border pl-2 py-1">
                {items.map(({ title: label, href, icon: ChildIcon }) => {
                  const isSelected = navItemActive(href, pathname);
                  return <Link key={href} href={href} aria-current={isSelected ? "page" : undefined} onClick={() => setMobileOpen(false)} className={`flex min-h-9 items-center gap-2 rounded-lg px-2.5 py-1.5 text-[12px] transition-colors duration-(--motion-fast) ${isSelected ? "bg-brand-soft font-semibold text-brand-contrast" : "text-muted hover:bg-background hover:text-foreground"}`}><ChildIcon size={14} /><span>{label}</span></Link>;
                })}
              </div>}
            </section>;
          })}
        </div>
      </nav>
    </aside>
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <header className="flex h-[72px] shrink-0 items-center gap-3 border-b border-border bg-surface/90 px-3 backdrop-blur-sm sm:px-6">
        <button ref={menuButton} type="button" aria-label="Open navigation" aria-controls="admin-navigation" aria-expanded={mobileOpen} onClick={() => setMobileOpen(true)} className="flex h-10 w-10 items-center justify-center rounded-xl text-muted hover:bg-brand-soft hover:text-brand-contrast lg:hidden"><Menu size={20} /></button>
        {/* Page titles live in AdminPageHeader, never in the global app bar. */}
        <span className="truncate text-[13px] font-semibold text-muted sm:text-[14px]">Platform console</span>
        <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:gap-3">
          <button type="button" aria-label="Toggle light or dark theme" title="Toggle theme" onClick={toggleTheme} className="flex h-9 w-9 items-center justify-center rounded-xl text-muted hover:bg-brand-soft hover:text-brand-contrast"><SunMoon size={17} /></button>
          <ContextMenu
            label={`Account actions for ${access.username}`}
            trigger={<><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand">{initials}</span><span className="hidden max-w-36 truncate text-[13px] font-semibold xl:block">{access.username}</span></>}
            triggerClassName="flex min-h-10 items-center gap-2 rounded-lg p-1 text-left transition-colors hover:bg-background"
            header={<div className="flex min-w-56 items-center gap-3 px-1 py-1"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand">{initials}</span><div className="min-w-0"><p className="truncate text-[13px] font-semibold text-foreground">{access.username}</p><p className="max-w-48 truncate text-[11px] text-muted">{access.email || "Platform administrator"}</p><p className="mt-0.5 text-[11px] font-medium text-brand-contrast">Platform Admin</p></div></div>}
            actions={accountActions}
          />
        </div>
      </header>
      <main id="admin-main" className="min-h-0 flex-1 overflow-y-auto"><div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6">{children}</div></main>
      {actionError && <div className="fixed bottom-4 left-4 z-[80] w-[min(24rem,calc(100vw-2rem))]"><Toast title="Account action failed" variant="error" onDismiss={clearActionError}>{actionError}</Toast></div>}
    </div>
  </div>;
}
