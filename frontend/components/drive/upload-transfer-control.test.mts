import assert from "node:assert/strict";
import test from "node:test";
import { UploadPausedError, UploadTransferControl } from "./upload-transfer-control.ts";

test("pausing aborts PUT transport without canceling the manager signal", async () => {
  const outer = new AbortController();
  const transfer = new UploadTransferControl(outer.signal);
  transfer.pause();
  assert.equal(transfer.paused, true);
  assert.equal(transfer.signal.aborted, true);
  assert.equal(outer.signal.aborted, false);
  assert.throws(() => transfer.throwIfPaused(), UploadPausedError);
  transfer.finish();
  await transfer.finished;
});

test("user cancellation interrupts transfer but is never misreported as pause", () => {
  const outer = new AbortController();
  const transfer = new UploadTransferControl(outer.signal);
  outer.abort();
  assert.equal(transfer.signal.aborted, true);
  assert.equal(transfer.paused, false);
  assert.doesNotThrow(() => transfer.throwIfPaused());
  transfer.finish();
});

test("user cancellation takes precedence over a simultaneous pause", () => {
  const outer = new AbortController();
  const transfer = new UploadTransferControl(outer.signal);
  transfer.pause();
  outer.abort();
  assert.equal(transfer.paused, false);
  transfer.finish();
});

test("finishing wakes a paused caller and prevents a late pause", async () => {
  const transfer = new UploadTransferControl(new AbortController().signal);
  const finished = transfer.finished;
  transfer.finish();
  transfer.finish();
  await finished;
  assert.throws(() => transfer.pause(), /no longer pausable/);
});

test("already canceled transfers are never pausable", () => {
  const outer = new AbortController();
  outer.abort();
  const transfer = new UploadTransferControl(outer.signal);
  assert.equal(transfer.signal.aborted, true);
  assert.throws(() => transfer.pause(), /no longer pausable/);
  transfer.finish();
});
