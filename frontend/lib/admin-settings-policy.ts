export type AdminSettingsDraft = { display_name: string; reason: string; revision: number };

/** Browser-side usability only. Django remains the authorization/validation boundary. */
export function validateAdminSettingsDraft(
  draft: AdminSettingsDraft,
  currentName: string,
): string | null {
  const name = draft.display_name.trim();
  const reason = draft.reason.trim();
  if (name.length < 2 || name.length > 80 || /[\u0000-\u001f\u007f]/u.test(draft.display_name)) {
    return "Display name must contain 2–80 printable characters.";
  }
  if (name === currentName) return "No change to save.";
  if (reason.length < 8 || reason.length > 500 || /[\u0000-\u001f\u007f]/u.test(draft.reason)) {
    return "Provide an audit reason of 8–500 printable characters.";
  }
  if (!Number.isSafeInteger(draft.revision) || draft.revision < 0 || draft.revision > 2147483647) {
    return "Invalid settings version. Reload this page.";
  }
  return null;
}

export function effectiveSessionPolicy(seconds: number, browserClose: boolean): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "Unavailable";
  const age = seconds % 60 === 0 ? `${seconds / 60} minutes` : `${seconds} seconds`;
  return `${age} maximum cookie age${browserClose ? "; expires at browser close" : ""}`;
}
