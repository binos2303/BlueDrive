import assert from "node:assert/strict";
import test from "node:test";
import { UploadProgressTelemetry } from "./upload-progress-telemetry.ts";

test("caps UI emissions even when transport fires thousands of progress events", () => {
  let now = 0;
  const telemetry = new UploadProgressTelemetry(50_000, 0, () => now);
  let emitted = 0;
  for (let i = 0; i <= 10_000; i++) {
    now = i; // 10 seconds
    if (telemetry.report(Math.min(i * 5, 50_000))) emitted++;
  }
  assert.ok(emitted >= 60 && emitted <= 70, `unexpected emission count: ${emitted}`);
});

test("resumed bytes do not become new throughput", () => {
  let now = 0;
  const telemetry = new UploadProgressTelemetry(1000, 500, () => now);
  assert.equal(telemetry.report(500)?.bytesPerSecond, undefined);
  now = 1000;
  const value = telemetry.report(700);
  assert.equal(value?.bytesPerSecond, 200);
  assert.equal(value?.etaSeconds, 1.5);
});

test("rollback caused by retry clears obsolete rate and ETA", () => {
  let now = 0;
  const telemetry = new UploadProgressTelemetry(1000, 0, () => now);
  telemetry.report(100);
  now = 1000;
  assert.equal(telemetry.report(600)?.bytesPerSecond, 600);
  now = 1100;
  const reset = telemetry.report(200);
  assert.equal(reset?.uploadedBytes, 200);
  assert.equal(reset?.bytesPerSecond, undefined);
  assert.equal(reset?.etaSeconds, undefined);
  now = 1600;
  const retransmitted = telemetry.report(400);
  assert.equal(retransmitted?.bytesPerSecond, 400);
  assert.equal(retransmitted?.etaSeconds, 1.5);
});

test("forced completion and progress clamp always emit", () => {
  let now = 0;
  const telemetry = new UploadProgressTelemetry(200, 0, () => now);
  telemetry.report(0);
  now = 10;
  assert.equal(telemetry.report(100), null);
  assert.equal(telemetry.report(500, true)?.uploadedBytes, 200);
  assert.equal(telemetry.report(Number.NaN, true)?.uploadedBytes, 200);
});

test("idle periods do not report stale speeds", () => {
  let now = 0;
  const telemetry = new UploadProgressTelemetry(1000, 0, () => now);
  telemetry.report(0);
  now = 1000;
  assert.equal(telemetry.report(100)?.bytesPerSecond, 100);
  now = 11000;
  assert.equal(telemetry.report(100)?.bytesPerSecond, undefined);
});

test("invalid parameters are rejected", () => {
  assert.throws(() => new UploadProgressTelemetry(-1), RangeError);
  assert.throws(() => new UploadProgressTelemetry(10, 11), RangeError);
  assert.throws(() => new UploadProgressTelemetry(10, 0, () => 0, -1), RangeError);
});
