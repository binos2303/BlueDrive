"use client";

import { useEffect, type ReactNode } from "react";
import { readThemePreference, resolveTheme, THEME_CHANGED_EVENT } from "@/lib/theme";

export default function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    const apply = () => {
      const resolved = resolveTheme(readThemePreference());
      document.documentElement.dataset.theme = resolved;
      document.documentElement.style.colorScheme = resolved;
    };

    apply();
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    window.addEventListener(THEME_CHANGED_EVENT, apply);
    window.addEventListener("storage", apply);
    media.addEventListener("change", apply);
    return () => {
      window.removeEventListener(THEME_CHANGED_EVENT, apply);
      window.removeEventListener("storage", apply);
      media.removeEventListener("change", apply);
    };
  }, []);

  return children;
}
