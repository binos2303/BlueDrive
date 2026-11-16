/**
 * Memory-bounded file hashing, intentionally independent of a particular hash
 * package so it can be tested against Node's SHA-256 reference implementation.
 *
 * Hashing chunk hashes together is NOT SHA-256(file). The stateful hasher must
 * process the original bytes in their original order.
 */
export interface IncrementalSha256 {
  update(bytes: Uint8Array): unknown;
  digest(): Uint8Array;
  destroy?(): void;
}

export type HashFileOptions = {
  signal?: AbortSignal;
  chunkSize?: number;
  /** Yield after approximately this many bytes to keep the browser responsive. */
  yieldEveryBytes?: number;
  /** Test seam; production uses setTimeout(0). */
  yieldToEventLoop?: () => Promise<void>;
};

const DEFAULT_CHUNK_BYTES = 2 * 1024 * 1024;
const MAX_CHUNK_BYTES = 16 * 1024 * 1024;
const DEFAULT_YIELD_BYTES = 8 * 1024 * 1024;

function assertNotAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException("File hashing was interrupted.", "AbortError");
}

export async function sha256HexIncremental(
  blob: Blob,
  newHasher: () => IncrementalSha256,
  options: HashFileOptions = {},
): Promise<string> {
  const chunkSize = options.chunkSize ?? DEFAULT_CHUNK_BYTES;
  if (!Number.isSafeInteger(chunkSize) || chunkSize <= 0 || chunkSize > MAX_CHUNK_BYTES) {
    throw new RangeError(`Hash chunk size must be between 1 and ${MAX_CHUNK_BYTES} bytes.`);
  }
  const yieldEveryBytes = options.yieldEveryBytes ?? DEFAULT_YIELD_BYTES;
  if (!Number.isSafeInteger(yieldEveryBytes) || yieldEveryBytes < 0) {
    throw new RangeError("Hash yielding interval must be a nonnegative safe integer.");
  }
  if (!Number.isSafeInteger(blob.size) || blob.size < 0) {
    throw new RangeError("File size must be a nonnegative safe integer.");
  }

  assertNotAborted(options.signal);
  const hasher = newHasher();
  let bytesSinceYield = 0;
  try {
    for (let start = 0; start < blob.size; start += chunkSize) {
      assertNotAborted(options.signal);
      const end = Math.min(start + chunkSize, blob.size);
      // At most one source slice is materialized at a time. Never use
      // blob.arrayBuffer() on the complete file.
      const bytes = new Uint8Array(await blob.slice(start, end).arrayBuffer());
      assertNotAborted(options.signal);
      hasher.update(bytes);
      bytesSinceYield += bytes.byteLength;
      if (yieldEveryBytes && bytesSinceYield >= yieldEveryBytes && end < blob.size) {
        bytesSinceYield = 0;
        await (options.yieldToEventLoop?.() ?? new Promise<void>((resolve) => setTimeout(resolve, 0)));
        assertNotAborted(options.signal);
      }
    }
    assertNotAborted(options.signal);
    const digest = hasher.digest();
    if (digest.length !== 32) throw new Error("Invalid SHA-256 digest length.");
    return Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
  } finally {
    // Some implementations zeroize internal state in destroy(). It is safe to
    // call after digest() as well as on exceptions/cancellation.
    hasher.destroy?.();
  }
}
