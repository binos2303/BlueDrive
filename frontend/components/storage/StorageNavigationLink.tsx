"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Database } from "lucide-react";
import { storageGet, type StorageCapabilities } from "@/lib/storage-control-service";

export default function StorageNavigationLink({ tenantId, onNavigate }: { tenantId?: string; onNavigate: () => void }) {
  const pathname = usePathname();
  const [allowed, setAllowed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    storageGet<StorageCapabilities>({ tenantId }, "capabilities/", controller.signal).then((data) => {
      if (!controller.signal.aborted) { setAllowed(data.permissions["storage.view"] === true); }
    }).catch(() => { if (!controller.signal.aborted) setAllowed(false); });
    return () => controller.abort();
  }, [tenantId]);
  if (!allowed) return null;
  const href = tenantId ? "/organization/storage" : "/admin/infrastructure/topology";
  const active = pathname === href;
  return <Link href={href} aria-current={active ? "page" : undefined} onClick={onNavigate} className={`flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm ${active ? "bg-brand-soft font-semibold text-brand-contrast" : "font-medium text-muted hover:bg-background hover:text-foreground"}`}><Database size={17} /><span>{tenantId ? "Organization storage" : "Platform storage"}</span></Link>;
}
