"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, ChevronDown, LayoutDashboard, LogOut, Menu, ShieldAlert, Users, X } from "lucide-react";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { useAccount } from "@/components/account/AccountProvider";

const sections = [
  { title: "Overview", icon: LayoutDashboard, items: [{ title: "Dashboard", href: "/admin" }] },
  { title: "Management", icon: Users, items: [{ title: "Users", href: "/admin/users" }, { title: "Files", href: "/admin/files" }] },
  { title: "Monitoring", icon: Activity, items: [{ title: "User Activity", href: "/admin/activity" }, { title: "Audit Logs", href: "/admin/audit" }, { title: "Storage & Quotas", href: "/admin/infrastructure/quotas" }] },
  { title: "Security", icon: ShieldAlert, items: [{ title: "Security Alerts", href: "/admin/security/alerts" }] },
] as const;

// Keep this in sync with the Django origin used by the existing account API.
const apiOrigin = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

type Access = { allowed: boolean; username: string; email: string };
export default function AdminConsole({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { state, signOut } = useAccount();
  const [access, setAccess] = useState<Access | null>(null);
  const [error, setError] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  useEffect(() => {
    if (state.status !== "loaded") return;
    if (!state.account) return;
    const controller = new AbortController();
    fetch(`${apiOrigin}/accounts/api/admin/access/`, { credentials: "include", signal: controller.signal, cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 403 ? "This account does not have platform administrator access." : "Cannot verify administrator access. Check your API connection.");
        return response.json() as Promise<Access>;
      })
      .then((result) => { setAccess(result); setError(""); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Access check failed."); });
    return () => controller.abort();
  }, [state.status]);
  const activeSection = sections.find((section) => section.items.some((item) => pathname === item.href || (item.href !== "/admin" && pathname.startsWith(`${item.href}/`))))?.title;
  function isOpen(title: string) { return expanded[title] ?? title === activeSection; }
  if (state.status === "error") return <main className="flex min-h-screen items-center justify-center p-6"><div className="max-w-md text-center"><h1 className="text-xl font-semibold">Sign in required</h1><p className="mt-2 text-sm text-muted">{state.error}</p><Link href="/login?next=%2Fadmin" className="mt-4 inline-block text-brand">Sign in</Link></div></main>;
  if (state.status !== "loaded" || (!access && !error)) return <main className="flex min-h-screen items-center justify-center bg-background text-muted">Verifying administrator access…</main>;
  if (error || !access?.allowed) return <main className="flex min-h-screen items-center justify-center bg-background px-5"><div className="w-full max-w-md rounded-2xl border border-border bg-surface p-7"><h1 className="text-xl font-semibold">Administrator access required</h1><p className="mt-3 text-sm text-muted">{error || "Access denied."}</p><div className="mt-6 flex gap-4 text-sm"><Link href="/login?next=%2Fadmin" className="font-semibold text-brand">Sign in as admin</Link><Link href="/drive" className="text-muted">Back to Drive</Link></div></div></main>;
  return <div className="min-h-screen bg-background text-foreground">
    {mobileOpen && <button aria-label="Close menu" className="fixed inset-0 z-30 bg-black/30 lg:hidden" onClick={() => setMobileOpen(false)} />}
    <aside className={`fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-border bg-surface transition-transform lg:translate-x-0 ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}>
      <div className="flex h-[72px] items-center justify-between border-b border-border px-4"><Link href="/admin"><BrandLogo className="text-lg" /></Link><button className="lg:hidden" aria-label="Close menu" onClick={() => setMobileOpen(false)}><X size={18} /></button></div>
      <nav className="min-h-0 flex-1 overflow-y-auto px-3 py-4" aria-label="Admin navigation">
        {sections.map(({ title, icon: Icon, items }) => <div key={title} className="mb-2">
          <button type="button" aria-expanded={isOpen(title)} aria-controls={`admin-group-${title}`} onClick={() => setExpanded((old) => ({ ...old, [title]: !isOpen(title) }))} className={`flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-semibold transition hover:bg-brand-soft ${title === activeSection ? "text-brand" : "text-foreground"}`}><Icon size={18} /><span className="flex-1">{title}</span><ChevronDown size={16} className={`transition-transform ${isOpen(title) ? "rotate-180" : ""}`} /></button>
          {isOpen(title) && <div id={`admin-group-${title}`} className="ml-5 space-y-1 border-l border-border pl-3 py-1">{items.map((item) => { const selected = pathname === item.href || (item.href !== "/admin" && pathname.startsWith(`${item.href}/`)); return <Link key={item.href} href={item.href} aria-current={selected ? "page" : undefined} onClick={() => setMobileOpen(false)} className={`block rounded-lg px-3 py-2 text-[13px] transition ${selected ? "bg-brand-soft font-semibold text-brand" : "text-muted hover:bg-background hover:text-foreground"}`}>{item.title}</Link>; })}</div>}
        </div>)}
      </nav><div className="border-t border-border p-4"><p className="truncate text-sm font-semibold">{access.username}</p><p className="truncate text-xs text-muted">{access.email}</p><button className="mt-3 flex items-center gap-2 text-xs text-muted hover:text-foreground" onClick={() => void signOut()}><LogOut size={14} />Sign out</button></div>
    </aside>
    <div className="min-h-screen lg:pl-60"><header className="sticky top-0 z-20 flex h-[72px] items-center gap-3 border-b border-border bg-surface/90 px-5 backdrop-blur"><button className="lg:hidden" aria-label="Open menu" onClick={() => setMobileOpen(true)}><Menu size={21} /></button><span className="text-sm font-semibold">BlueDrive Administration</span><span className="ml-auto rounded-full bg-brand-soft px-3 py-1 text-xs font-semibold text-brand">Platform Admin</span></header><main className="mx-auto w-full max-w-[1440px] p-4 sm:p-6">{children}</main></div>
  </div>;
}
