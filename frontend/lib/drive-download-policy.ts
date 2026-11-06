/** Small, side-effect-free rules shared by Drive download UI and transport. */
export function isDownloadSelectionSupported(items: readonly { type: string }[]): boolean {
  if (items.length === 0) return false;
  const folderCount = items.filter((item) => item.type === "folder").length;
  return folderCount === 0 || (folderCount === 1 && items.length === 1);
}

export function isExpectedDownloadMimeType(actual: string | null, expected: string): boolean {
  return actual?.split(";", 1)[0].trim().toLowerCase() === expected.toLowerCase();
}
