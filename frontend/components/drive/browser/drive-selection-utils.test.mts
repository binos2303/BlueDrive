import assert from "node:assert/strict";
import test from "node:test";
import { nextSelectedIds } from "./drive-selection-utils.ts";

const order = [10, 20, 30, 40, 50];
const plain = { shiftKey: false, ctrlKey: false, metaKey: false };
const ctrl = { ...plain, ctrlKey: true };
const cmd = { ...plain, metaKey: true };
const shift = { ...plain, shiftKey: true };
const shiftCtrl = { ...shift, ctrlKey: true };
const shiftCmd = { ...shift, metaKey: true };

const values = (ids: ReadonlySet<number>) => [...ids].sort((a, b) => a - b);

test("single click selects only the clicked item", () => {
  assert.deepEqual(values(nextSelectedIds(new Set([10, 20]), order, 40, 20, plain)), [40]);
});

test("Ctrl/Cmd click toggles an item without clearing other selections", () => {
  assert.deepEqual(values(nextSelectedIds(new Set([10, 30]), order, 30, 10, ctrl)), [10]);
  assert.deepEqual(values(nextSelectedIds(new Set([10, 30]), order, 40, 10, cmd)), [10, 30, 40]);
});

test("Shift click selects an inclusive range in displayed sort order", () => {
  assert.deepEqual(values(nextSelectedIds(new Set([50]), order, 40, 20, shift)), [20, 30, 40]);
  assert.deepEqual(values(nextSelectedIds(new Set([20]), order, 20, 40, shift)), [20, 30, 40]);
});

test("Shift+Ctrl/Cmd adds ranges instead of replacing current selection", () => {
  assert.deepEqual(values(nextSelectedIds(new Set([10, 50]), order, 40, 20, shiftCtrl)), [10, 20, 30, 40, 50]);
  assert.deepEqual(values(nextSelectedIds(new Set([10]), order, 40, 20, shiftCmd)), [10, 20, 30, 40]);
});

test("Shift click falls back to target when anchor is absent or no longer visible", () => {
  assert.deepEqual(values(nextSelectedIds(new Set([10]), order, 30, null, shift)), [30]);
  assert.deepEqual(values(nextSelectedIds(new Set([10]), order, 30, 999, shift)), [30]);
});

test("Unknown target does not change Shift selection", () => {
  assert.deepEqual(values(nextSelectedIds(new Set([20]), order, 999, 20, shift)), [20]);
});

test("Pure selection helper does not mutate caller-owned selection", () => {
  const old = new Set([10, 20]);
  const result = nextSelectedIds(old, order, 20, 10, ctrl);
  assert.deepEqual(values(old), [10, 20]);
  assert.deepEqual(values(result), [10]);
});

test("Shift range follows current display order, not numeric file IDs", () => {
  const descending = [50, 40, 10, 30, 20];
  assert.deepEqual(values(nextSelectedIds(new Set(), descending, 30, 40, shift)), [10, 30, 40]);
});
