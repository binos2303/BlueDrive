"use client";

import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import Sidebar from "./Sidebar";
import SettingsSidebar from "./SettingsSidebar";
import Header from "./Header";

export default function DashboardShell({
  children,
  settingsNavigation,
}: {
  children: ReactNode;
  settingsNavigation?: { active: string; onChange: (section: string) => void };
}) {
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const navigationRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const wasNavigationOpen = useRef(false);

  useEffect(() => {
    if (mobileNavigationOpen) {
      navigationRef.current?.querySelector("a")?.focus();
    } else if (wasNavigationOpen.current) {
      menuButtonRef.current?.focus();
    }
    wasNavigationOpen.current = mobileNavigationOpen;
  }, [mobileNavigationOpen]);

  useEffect(() => {
    if (!mobileNavigationOpen) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMobileNavigationOpen(false);
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = navigationRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable?.length) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [mobileNavigationOpen]);

  return (
    <main className="flex h-screen overflow-hidden bg-background">
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
          onNavigate={() => setMobileNavigationOpen(false)} />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <Header
          menuButtonRef={menuButtonRef}
          mobileOpen={mobileNavigationOpen}
          onMenuClick={() => setMobileNavigationOpen(true)}
        />

        <div className="min-h-0 flex-1 overflow-y-auto">
          {children}
        </div>
      </div>
    </main>
  );
}