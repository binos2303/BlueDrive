import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { sha256HexIncremental } from "./upload-hash-core.ts";

function hasher() {
  const hash = createHash("sha256");
  return {
    update(bytes: Uint8Array) { hash.update(bytes); },
    digest() { return new Uint8Array(hash.digest()); },
  };
}
function expected(bytes: Uint8Array) {
  return createHash("sha256").update(bytes).digest("hex");
}

test("SHA-256 matches reference for empty input and known FIPS abc vector", async () => {
  assert.equal(await sha256HexIncremental(new Blob([]), hasher),
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  assert.equal(await sha256HexIncremental(new Blob(["abc"]), hasher, { chunkSize: 1 }),
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});

test("hashes actual bytes in order across chunk boundaries", async () => {
  const bytes = Uint8Array.from({ length: 1_200_013 }, (_, i) => (i * 37 + 5) % 256);
  assert.equal(
    await sha256HexIncremental(new Blob([bytes]), hasher, { chunkSize: 137_003, yieldEveryBytes: 0 }),
    expected(bytes),
  );
});

test("never materializes full source Blob and bounds individual slice length", async () => {
  const source = new Blob([new Uint8Array(1024)]);
  const forbidden = new Proxy(source, {
    get(target, prop) {
      if (prop === "arrayBuffer") throw new Error("full-file arrayBuffer() is forbidden");
      if (prop === "slice") return (start: number, end: number) => {
        assert.ok(end - start <= 127);
        return target.slice(start, end);
      };
      return Reflect.get(target, prop, target);
    },
  });
  assert.equal(await sha256HexIncremental(forbidden, hasher, { chunkSize: 127 }),
    expected(new Uint8Array(1024)));
});

test("aborted before starting: no hashing or reads", async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    sha256HexIncremental(new Blob(["abc"]), () => { throw new Error("should not create hasher"); }, { signal: controller.signal }),
    { name: "AbortError" },
  );
});

test("aborted during hashing: stop before reading the next chunk and release state", async () => {
  const controller = new AbortController();
  let updates = 0;
  let destroyed = 0;
  const hash = createHash("sha256");
  await assert.rejects(
    sha256HexIncremental(new Blob([new Uint8Array(12)]), () => ({
      update(bytes: Uint8Array) { updates++; hash.update(bytes); controller.abort(); },
      digest() { return new Uint8Array(hash.digest()); },
      destroy() { destroyed++; },
    }), { signal: controller.signal, chunkSize: 4 }),
    { name: "AbortError" },
  );
  assert.equal(updates, 1);
  assert.equal(destroyed, 1);
});

test("aborted while yielding: no additional chunk is read", async () => {
  const controller = new AbortController();
  let chunks = 0;
  await assert.rejects(
    sha256HexIncremental(new Blob([new Uint8Array(8)]), () => ({
      update() { chunks++; },
      digest() { return new Uint8Array(32); },
    }), {
      signal: controller.signal,
      chunkSize: 2,
      yieldEveryBytes: 2,
      async yieldToEventLoop() { controller.abort(); },
    }),
    { name: "AbortError" },
  );
  assert.equal(chunks, 1);
});

test("rejects unsafe chunk sizes and non SHA-256 digests", async () => {
  for (const chunkSize of [0, -1, NaN, 16 * 1024 * 1024 + 1]) {
    await assert.rejects(sha256HexIncremental(new Blob([]), hasher, { chunkSize }), RangeError);
  }
  await assert.rejects(
    sha256HexIncremental(new Blob([]), () => ({ update() {}, digest: () => new Uint8Array(16) })),
    /Invalid SHA-256 digest length/,
  );
});
