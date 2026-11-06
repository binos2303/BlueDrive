/** UI preview policy must be no more permissive than Django's file_view allowlist. */
const INLINE_PREVIEW_TYPES = new Set([
  "image/jpeg", "image/png", "image/gif", "image/webp", "text/plain",
]);

export const MAX_PREVIEW_BYTES = 15 * 1024 * 1024;

export function normalizePreviewMimeType(value: string): string {
  return value.split(";")[0].trim().toLowerCase();
}

export function isPreviewSupported(value: string): boolean {
  return INLINE_PREVIEW_TYPES.has(normalizePreviewMimeType(value));
}

export function isPreviewSizeAllowed(bytes: number): boolean {
  return Number.isSafeInteger(bytes) && bytes >= 0 && bytes <= MAX_PREVIEW_BYTES;
}
