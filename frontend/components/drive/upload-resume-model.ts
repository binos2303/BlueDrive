/**
 * Chỉ lưu ETag do kho trả về để tiếp tục phần đã tải, không lưu URL ký tạm.
 * Backend đối chiếu lại toàn bộ danh sách phần với kho đã ghim trước publication.
 */
export function restorePartReceipts(
  serialized: string | null,
  sessionId: string,
  partCount: number,
): Map<number, string> {
  const result = new Map<number, string>();
  if (!serialized || !Number.isSafeInteger(partCount) || partCount < 0) return result;
  try {
    const value: unknown = JSON.parse(serialized);
    if (!value || typeof value !== "object") return result;
    const record = value as { sessionId?: unknown; parts?: unknown };
    if (record.sessionId !== sessionId || !Array.isArray(record.parts) || record.parts.length > partCount) return result;
    for (const part of record.parts) {
      if (!Array.isArray(part) || part.length !== 2) return new Map();
      const [number, etag] = part;
      if (!Number.isSafeInteger(number) || number < 1 || number > partCount ||
          typeof etag !== "string" || !etag || etag.length > 256 || /[\r\n]/.test(etag) || result.has(number)) {
        return new Map();
      }
      result.set(number, etag);
    }
  } catch {
    return new Map();
  }
  return result;
}

export function serializePartReceipts(sessionId: string, completed: ReadonlyMap<number, string>): string {
  return JSON.stringify({ sessionId, parts: [...completed].sort(([a], [b]) => a - b) });
}

export type ProviderPart = { part_number: number; etag: string; size_bytes: number };

/** Keep only client-uploaded receipts that still match the provider. */
export function reconcilePartReceipts(
  receipts: ReadonlyMap<number, string>,
  providerParts: readonly ProviderPart[],
  fileSize: number,
  partSize: number,
): Map<number, string> {
  const provider = new Map(providerParts.map((part) => [part.part_number, part]));
  return new Map([...receipts].filter(([number, etag]) => {
    const part = provider.get(number);
    const expectedSize = Math.min(partSize, fileSize - (number - 1) * partSize);
    return part?.etag === etag && part.size_bytes === expectedSize && expectedSize > 0;
  }));
}
