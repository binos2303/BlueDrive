export type ThemePreference = "system" | "light" | "dark";

export const THEME_CHANGED_EVENT = "securedrive:theme-changed";
const THEME_KEY = "securedrive:theme-preference:v1";

export function readThemePreference(): ThemePreference {
  if (typeof window === "undefined") return "system";
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" || value === "system" ? value : "system";
  } catch {
    return "system";
  }
}

export function setThemePreference(preference: ThemePreference): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(THEME_KEY, preference);
  } catch {
    // The current page still applies the preference even if browser storage is blocked.
  }
  window.dispatchEvent(new Event(THEME_CHANGED_EVENT));
}

export function resolveTheme(preference: ThemePreference): "light" | "dark" {
  if (preference === "light" || preference === "dark") return preference;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
