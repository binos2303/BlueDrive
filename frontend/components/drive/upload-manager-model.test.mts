import assert from "node:assert/strict";
import test from "node:test";
import {
  createUploadTask,
  confirmTaskCompleted,
  markDuplicateTasks,
  retryTask,
  transitionTask,
} from "./upload-manager-model.ts";

function task() {
  return createUploadTask({
    id: "upload-1",
    fileName: "report.pdf",
    relativePath: "report.pdf",
    mimeType: "application/pdf",
    size: 512,
    destinationId: null,
  });
}

test("state transitions follow service-reported lifecycle and reject unconfirmed completion", () => {
  let current = transitionTask(task(), "preparing");
  current = transitionTask(current, "uploading", {
    progress: { uploadedBytes: 128, totalBytes: 512 },
    uploadSessionId: "session-1",
  });
  current = transitionTask(current, "verifying");
  current = transitionTask(current, "scanning");
  assert.throws(() => confirmTaskCompleted(current, false), /requires backend confirmation/);
  current = confirmTaskCompleted(current, true);
  assert.equal(current.status, "completed");
  assert.equal(current.uploadSessionId, "session-1");
  assert.throws(() => transitionTask(task(), "completed"), /Use confirmTaskCompleted/);
});

test("retry is bounded and disallowed for non-retryable failures", () => {
  let current = transitionTask(task(), "preparing");
  current = transitionTask(current, "failed", {
    error: "Temporary storage outage",
    retryPolicy: { retries: 0, maxRetries: 2, retryable: true },
  });
  current = retryTask(current);
  assert.equal(current.status, "queued");
  assert.equal(current.retryPolicy.retries, 1);
  current = transitionTask(current, "failed", {
    error: "Temporary storage outage",
    retryPolicy: { ...current.retryPolicy, retries: 2 },
  });
  assert.throws(() => retryTask(current), /Retry limit reached/);

  const invalid = createUploadTask({
    id: "invalid",
    fileName: "bad",
    relativePath: "../bad",
    mimeType: "",
    size: 1,
    destinationId: null,
    validationError: "Invalid path",
  });
  assert.throws(() => retryTask(invalid), /Invalid path/);
});

test("queued and in-flight uploads can be canceled and cannot later complete", () => {
  assert.equal(transitionTask(task(), "canceled").status, "canceled");
  const inFlight = transitionTask(transitionTask(task(), "preparing"), "uploading");
  assert.equal(transitionTask(inFlight, "canceled").status, "canceled");
  assert.throws(
    () => confirmTaskCompleted(transitionTask(inFlight, "canceled"), true),
    /Invalid upload transition/,
  );
});

test("duplicate paths are marked without choosing an overwrite policy", () => {
  const first = task();
  const second = createUploadTask({
    id: "upload-2",
    fileName: "REPORT.PDF",
    relativePath: "REPORT.PDF",
    mimeType: first.mimeType,
    size: first.size,
    destinationId: null,
  });
  const [a, b] = markDuplicateTasks([first, second]);
  assert.equal(a.duplicate, true);
  assert.equal(b.duplicate, true);
  assert.equal(a.conflictResolution, null);
});
