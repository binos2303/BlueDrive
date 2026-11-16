export function workspaceIdFromPathname(pathname: string): string | null {
  const encoded = pathname.match(/^\/drive\/workspaces\/([^/]+)(?:\/|$)/)?.[1];
  if (!encoded) return null;
  try { return decodeURIComponent(encoded); } catch { return encoded; }
}

export function drivePath(workspaceId: string | null, section = "files"): string {
  if (workspaceId) return `/drive/workspaces/${encodeURIComponent(workspaceId)}/${section}`;
  return section === "files" ? "/drive" : `/drive/${section}`;
}

export function driveFolderIdFromPathname(pathname: string): number | null {
  const match = pathname.match(/^\/drive\/(?:workspaces\/[^/]+\/)?folders\/([1-9]\d*)\/?$/);
  const id = match ? Number(match[1]) : NaN;
  return Number.isSafeInteger(id) ? id : null;
}
