"use client";

import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAccount } from "@/components/account/AccountProvider";

import Sidebar from "./Sidebar";
import SettingsSidebar from "./SettingsSidebar";
import Header from "./Header";
import useNavigationDrawer from "./useNavigationDrawer";
import GlobalDriveActions from "@/components/drive/GlobalDriveActions";
import type { OrganizationWorkspace } from "@/lib/workspace-service";
import { SelectedWorkspaceContext } from "@/components/workspaces/SelectedWorkspaceContext";
import { SharedFolderContext } from "@/components/drive/browser/SharedFolderContext";

export default function DashboardShell({
  children,
  settingsNavigation,
}: {
  children: ReactNode;
  settingsNavigation?: { active: string; onChange: (section: string) => void };
}) {
  const router = useRouter();
  const { state } = useAccount();
  useEffect(() => {
    if (state.status === "loaded" && state.account?.is_platform_admin) router.replace("/admin");
  }, [state, router]);
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const [workspace, setWorkspace] = useState<OrganizationWorkspace | null>(null);
  const [sharedFolderId, setSharedFolderId] = useState<number | null>(null);
  const navigationRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  useNavigationDrawer(mobileNavigationOpen, setMobileNavigationOpen, navigationRef, menuButtonRef);

  if (state.status === "loaded" && state.account?.is_platform_admin) return null;

  return (
    <SelectedWorkspaceContext.Provider value={workspace}><SharedFolderContext.Provider value={{ folderId: sharedFolderId, setFolderId: setSharedFolderId }}><main className="flex h-dvh overflow-hidden bg-background">
      {mobileNavigationOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setMobileNavigationOpen(false)}
          className="fixed inset-0 z-40 bg-foreground/35 lg:hidden"
        />
      )}
      {settingsNavigation ? (
        <SettingsSidebar navigationRef={navigationRef} mobileOpen={mobileNavigationOpen}
          active={settingsNavigation.active} onChange={settingsNavigation.onChange}
          onNavigate={() => setMobileNavigationOpen(false)} />
      ) : (
        <Sidebar navigationRef={navigationRef} mobileOpen={mobileNavigationOpen}
          workspace={workspace}
          sharedFolderId={sharedFolderId}
          onNavigate={() => setMobileNavigationOpen(false)} />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <Header
          onWorkspaceChange={setWorkspace}
          menuButtonRef={menuButtonRef}
          mobileOpen={mobileNavigationOpen}
          onMenuClick={() => setMobileNavigationOpen(true)}
        />

        <div className="min-h-0 flex-1 overflow-y-auto">
          {children}
        </div>
      </div>
      <GlobalDriveActions />
    </main></SharedFolderContext.Provider></SelectedWorkspaceContext.Provider>
  );
}
