export const settingsTabs = ["general", "security", "privacy", "connections"] as const;
export type SettingsTab = (typeof settingsTabs)[number];

export function settingsTab(value: unknown): SettingsTab {
  return settingsTabs.find((tab) => tab === value) ?? "general";
}
