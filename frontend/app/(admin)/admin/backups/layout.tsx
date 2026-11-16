"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import AdminSegmentTabs from "@/components/admin/AdminSegmentTabs";

const tabs = [
  { value: "/admin/backups", label: "Overview", href: "/admin/backups" },
  { value: "/admin/backups/jobs", label: "Jobs", href: "/admin/backups/jobs" },
  { value: "/admin/backups/history", label: "History", href: "/admin/backups/history" },
  { value: "/admin/backups/policies", label: "Policies", href: "/admin/backups/policies" },
  { value: "/admin/backups/restore", label: "Restore", href: "/admin/backups/restore" },
] as const;

export default function BackupLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return <div className="space-y-5">
    <nav aria-label="Backup navigation"><AdminSegmentTabs value={pathname} tabs={tabs} label="Backup sections" /></nav>
    {children}
  </div>;
}
