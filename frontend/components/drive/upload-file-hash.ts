import { sha256 } from "@noble/hashes/sha2.js";
import { sha256HexIncremental, type HashFileOptions } from "./upload-hash-core";

// File/Blob bytes are immutable. Reuse the verified digest when the same File
// object is retried/resumed in this tab. Weak keys don't retain completed files.
const digestsByFile = new WeakMap<File, string>();

/** SHA-256 of the original file bytes, not of the individual chunk digests. */
export async function sha256File(file: File, options: HashFileOptions = {}): Promise<string> {
  if (options.signal?.aborted) throw new DOMException("File hashing was interrupted.", "AbortError");
  const cached = digestsByFile.get(file);
  if (cached) return cached;

  const digest = await sha256HexIncremental(file, () => sha256.create(), options);
  // A late cancellation must not mark a hash as completed for this invocation.
  if (options.signal?.aborted) throw new DOMException("File hashing was interrupted.", "AbortError");
  digestsByFile.set(file, digest);
  return digest;
}
