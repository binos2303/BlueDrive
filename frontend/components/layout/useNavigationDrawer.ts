"use client";

import { useEffect, useRef, type Dispatch, type RefObject, type SetStateAction } from "react";

/** Drive and admin drawers share the same keyboard and focus behavior. */
export default function useNavigationDrawer(open: boolean, setOpen: Dispatch<SetStateAction<boolean>>, navigation: RefObject<HTMLElement | null>, trigger: RefObject<HTMLButtonElement | null>) {
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open) navigation.current?.querySelector<HTMLElement>("a, button")?.focus();
    else if (wasOpen.current) trigger.current?.focus();
    wasOpen.current = open;
  }, [open, navigation, trigger]);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") { setOpen(false); return; }
      if (event.key !== "Tab") return;
      const focusable = Array.from(navigation.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? []).filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    const desktop = window.matchMedia("(min-width: 1024px)");
    const closeOnDesktop = () => { if (desktop.matches) setOpen(false); };
    desktop.addEventListener("change", closeOnDesktop);
    document.addEventListener("keydown", handleKeyDown);
    return () => { desktop.removeEventListener("change", closeOnDesktop); document.removeEventListener("keydown", handleKeyDown); };
  }, [open, setOpen, navigation]);
}
