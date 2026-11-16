export type ThemePreference = "system" | "light" | "dark";

export const THEME_CHANGED_EVENT = "securedrive:theme-changed";
const THEME_KEY = "securedrive:theme-preference:v1";

// Run while parsing the document, before the first paint; the provider keeps it in sync afterward.
export const THEME_INIT_SCRIPT = `(() => {
  let preference;
  try { preference = window.localStorage.getItem(${JSON.stringify(THEME_KEY)}); } catch {}
  const theme = preference === "light" || preference === "dark" ? preference
    : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
})();`;

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
