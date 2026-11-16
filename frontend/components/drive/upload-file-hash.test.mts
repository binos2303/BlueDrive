import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { sha256 } from "@noble/hashes/sha2.js";
import { sha256HexIncremental } from "./upload-hash-core.ts";

/** Run after npm install: verifies the real npm library, not a test double. */
test("@noble/hashes SHA-256 incremental matches native SHA-256 on multi-chunk input", async () => {
  const bytes = Uint8Array.from({ length: 4 * 1024 * 1024 + 99 }, (_, i) => (i * 31 + 17) & 255);
  const expected = createHash("sha256").update(bytes).digest("hex");
  const actual = await sha256HexIncremental(new Blob([bytes]), () => sha256.create(), {
    chunkSize: 1024 * 1024,
  });
  assert.equal(actual, expected);
});
