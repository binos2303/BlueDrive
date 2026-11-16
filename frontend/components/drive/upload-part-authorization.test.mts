import assert from "node:assert/strict";
import test from "node:test";
import { OnDemandPartAuthorizer } from "./upload-part-authorization.ts";

type Grant = { part_number: number; url: string };

function grant(n: number): Grant { return { part_number: n, url: `signed-${n}` }; }

test("issues only the needed group; shares authorization for concurrent workers", async () => {
  const batches: number[][] = [];
  const cache = new OnDemandPartAuthorizer<Grant>([1, 2, 3, 4, 5, 6, 7], 3, async (numbers) => {
    batches.push(numbers);
    await new Promise<void>((resolve) => setTimeout(resolve, 1));
    return numbers.map(grant);
  });
  const first = await Promise.all([cache.get(2), cache.get(1), cache.get(3)]);
  assert.deepEqual(first.map((item) => item.part_number), [2, 1, 3]);
  assert.deepEqual(batches, [[1, 2, 3]]);
  await cache.get(5);
  assert.deepEqual(batches, [[1, 2, 3], [4, 5, 6]]);
  await cache.get(7);
  assert.deepEqual(batches.at(-1), [7]);
  await cache.get(4);
  assert.equal(batches.length, 3);
});

test("failed authorization can retry without poisoning cache", async () => {
  let attempts = 0;
  const cache = new OnDemandPartAuthorizer<Grant>([1], 3, async (numbers) => {
    attempts += 1;
    if (attempts === 1) throw new Error("temporary network failure");
    return numbers.map(grant);
  });
  await assert.rejects(cache.get(1), /temporary/);
  assert.equal((await cache.get(1)).url, "signed-1");
  assert.equal(attempts, 2);
});

test("rejects malformed provider batches", async () => {
  const missing = new OnDemandPartAuthorizer<Grant>([1, 2], 2, async () => [grant(1)]);
  await assert.rejects(missing.get(1), /all requested/);
  const duplicate = new OnDemandPartAuthorizer<Grant>([1, 2], 2, async () => [grant(1), grant(1)]);
  await assert.rejects(duplicate.get(1), /duplicated/);
  const extraneous = new OnDemandPartAuthorizer<Grant>([1], 2, async () => [grant(3)]);
  await assert.rejects(extraneous.get(1), /unexpected/);
});

test("refresh overrides only one expired part", async () => {
  const cache = new OnDemandPartAuthorizer<Grant>([1, 2], 2, async (numbers) => numbers.map(grant));
  await cache.get(1);
  cache.replace({ part_number: 1, url: "refreshed" });
  assert.equal((await cache.get(1)).url, "refreshed");
  assert.equal((await cache.get(2)).url, "signed-2");
});

test("abort before and during authorizing prevents transmitting with expired context", async () => {
  const aborted = new AbortController();
  aborted.abort();
  const before = new OnDemandPartAuthorizer<Grant>([1], 1, async () => { throw Error("must not be called"); });
  await assert.rejects(before.get(1, aborted.signal), { name: "AbortError" });
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const during = new OnDemandPartAuthorizer<Grant>([1], 1, async () => { await gate; return [grant(1)]; });
  const controller = new AbortController();
  const pending = during.get(1, controller.signal);
  controller.abort();
  release();
  await assert.rejects(pending, { name: "AbortError" });
});

test("validates part ranges and maximum group size", async () => {
  assert.throws(() => new OnDemandPartAuthorizer([1, 1], 2, async () => []), RangeError);
  assert.throws(() => new OnDemandPartAuthorizer([1], 1001, async () => []), RangeError);
  const cache = new OnDemandPartAuthorizer<Grant>([2], 1, async () => [grant(2)]);
  await assert.rejects(cache.get(1), RangeError);
  assert.throws(() => cache.replace(grant(3)), RangeError);
});
