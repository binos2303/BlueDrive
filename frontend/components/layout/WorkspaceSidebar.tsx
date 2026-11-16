"use client";

import Link from "next/link";
import { ArrowLeft, Clock3, Files, Star, Trash2, Users } from "lucide-react";
import { clearActiveWorkspaceSelection } from "@/lib/workspace-context";
import type { OrganizationWorkspace } from "@/lib/workspace-service";
import DriveFolderNavigation from "./DriveFolderNavigation";
import { drivePath } from "@/lib/drive-paths";

export default function WorkspaceSidebar({ workspaceId, workspace, pathname, onNavigate }: {
  workspaceId: string;
  workspace: OrganizationWorkspace | null;
  pathname: string;
  onNavigate: () => void;
}) {
  const base = `/drive/workspaces/${encodeURIComponent(workspaceId)}`;
  const items = [
    { label: "Files", href: drivePath(workspaceId), icon: Files },
    { label: "Recent", href: drivePath(workspaceId, "recent"), icon: Clock3 },
    { label: "Starred", href: drivePath(workspaceId, "starred"), icon: Star },
    { label: "Trash", href: drivePath(workspaceId, "trash"), icon: Trash2 },
    ...(workspace?.canManage ? [
      { label: "Members", href: `${base}/members`, icon: Users },
      { label: "Activity log", href: `${base}/activity`, icon: Clock3 },
    ] : []),
  ];

  return <>
    <div className="mb-3 border-b border-border px-3 pb-4">
      <Link href="/drive" onClick={() => { clearActiveWorkspaceSelection(); onNavigate(); }} className="flex min-h-11 items-center gap-2 rounded-lg text-sm font-medium text-muted hover:text-foreground">
        <ArrowLeft size={16} className="shrink-0" /> My Drive
      </Link>
      <p className="mt-2 truncate text-sm font-semibold text-foreground" title={workspace?.name}>{workspace?.name || "Workspace"}</p>
      <p className="mt-1 text-xs leading-5 text-muted">{workspace?.currentUserRole ? `${workspace.currentUserRole.charAt(0).toUpperCase()}${workspace.currentUserRole.slice(1)} access` : "Shared workspace"}</p>
    </div>
    <nav aria-label="Workspace navigation" className="space-y-1">
      {items.map(({ label, href, icon: Icon }) => {
        if (href === drivePath(workspaceId)) return <DriveFolderNavigation key={workspaceId} label={label} icon={Icon} workspaceId={workspaceId} pathname={pathname} onNavigate={onNavigate} />;
        const active = pathname === href;
        return <Link key={href} href={href} onClick={onNavigate} aria-current={active ? "page" : undefined} className={`flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm transition-colors duration-(--motion-fast) ${active ? "bg-brand-soft font-semibold text-brand-contrast" : "font-medium text-muted hover:bg-background hover:text-foreground"}`}>
          <Icon size={18} className="shrink-0" /><span>{label}</span>
        </Link>;
      })}
    </nav>
  </>;
}
