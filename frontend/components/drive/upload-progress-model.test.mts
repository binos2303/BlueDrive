import assert from "node:assert/strict";
import test from "node:test";
import { UploadPartProgress } from "./upload-progress-model.ts";

test("accumulates simultaneous progress using deltas rather than recounting parts", () => {
  const progress = new UploadPartProgress(20, 8);
  assert.equal(progress.update(1, 5), 5);
  assert.equal(progress.update(2, 6), 11);
  assert.equal(progress.update(1, 7), 13);
  assert.equal(progress.update(2, 6), 13);
  assert.equal(progress.update(3, 8), 17); // final part is only 4 bytes
  assert.equal(progress.update(1, 8), 18);
  assert.equal(progress.update(2, 8), 20);
  assert.equal(progress.uploadedBytes, 20);
});

test("retry resets a failed part without losing progress on other parts", () => {
  const progress = new UploadPartProgress(16, 8);
  progress.update(1, 8);
  progress.update(2, 6);
  assert.equal(progress.update(2, 0), 8);
  assert.equal(progress.update(2, 8), 16);
});

test("filters invalid byte counts and part indexes", () => {
  const progress = new UploadPartProgress(9, 8);
  assert.equal(progress.update(2, Number.NaN), 0);
  assert.equal(progress.update(2, 1_000), 1);
  assert.throws(() => progress.update(3, 1), RangeError);
  assert.throws(() => progress.update(0, 1), RangeError);
  assert.throws(() => new UploadPartProgress(-1, 8), RangeError);
});
