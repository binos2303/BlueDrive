import assert from "node:assert/strict";
import test from "node:test";
import { reconcilePartReceipts, restorePartReceipts, serializePartReceipts } from "./upload-resume-model.ts";

test("persists and restores provider ETags in part order", () => {
  const receipts = new Map([[3, '"ccc"'], [1, '"aaa"']]);
  const stored = serializePartReceipts("session-1", receipts);
  assert.deepEqual([...restorePartReceipts(stored, "session-1", 3)], [[1, '"aaa"'], [3, '"ccc"']]);
});

test("ignores receipts from a different session", () => {
  assert.equal(restorePartReceipts(serializePartReceipts("old", new Map([[1, '"aaa"']])), "new", 1).size, 0);
});

test("rejects malformed, duplicate and out-of-range receipts", () => {
  for (const parts of [
    [[1, '"a"'], [1, '"b"']],
    [[0, '"a"']],
    [[2, '"a"']],
    [[1, "bad\rvalue"]],
    [[1, ""]],
  ]) {
    assert.equal(restorePartReceipts(JSON.stringify({ sessionId: "s", parts }), "s", 1).size, 0);
  }
  assert.equal(restorePartReceipts("invalid json", "s", 1).size, 0);
});

test("reconciles provider receipts; reuploads missing, overwritten or wrongly sized parts", () => {
  const local = new Map([[1, '"etag1"'], [2, '"etag2"'], [3, '"etag3"']]);
  const remote = [
    { part_number: 1, etag: '"etag1"', size_bytes: 8 },
    { part_number: 2, etag: '"different"', size_bytes: 8 },
    { part_number: 3, etag: '"etag3"', size_bytes: 7 },
  ];
  assert.deepEqual([...reconcilePartReceipts(local, remote, 19, 8)], [[1, '"etag1"']]);
});

test("reuses a valid short final part", () => {
  const result = reconcilePartReceipts(
    new Map([[1, '"ok1"'], [2, '"ok2"']]),
    [{ part_number: 1, etag: '"ok1"', size_bytes: 8 }, { part_number: 2, etag: '"ok2"', size_bytes: 3 }],
    11, 8,
  );
  assert.equal(result.size, 2);
});
