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


test("pause and resume preserve UploadSession and do not consume retry budget", () => {
  let current = transitionTask(task(), "preparing");
  current = transitionTask(current, "uploading", { uploadSessionId: "session-42" });
  current = transitionTask(current, "paused");
  assert.equal(current.uploadSessionId, "session-42");
  current = transitionTask(current, "queued");
  assert.equal(current.uploadSessionId, "session-42");
  assert.equal(current.retryPolicy.retries, 0);
  current = transitionTask(current, "preparing");
  assert.equal(current.status, "preparing");
});

test("the same path in My Drive and another workspace is not an upload conflict", () => {
  const personal = task();
  const inWorkspace = createUploadTask({ ...personal, id: "workspace-task", workspaceId: "workspace-a" });
  const anotherWorkspace = createUploadTask({ ...personal, id: "another-task", workspaceId: "workspace-b" });
  assert.deepEqual(markDuplicateTasks([personal, inWorkspace, anotherWorkspace]).map((entry) => entry.duplicate), [false, false, false]);
  const duplicate = createUploadTask({ ...inWorkspace, id: "duplicate-in-a" });
  assert.deepEqual(markDuplicateTasks([inWorkspace, duplicate]).map((entry) => entry.duplicate), [true, true]);
});

test("pause, retry and completion preserve the task's original workspace", () => {
  let current = createUploadTask({ ...task(), workspaceId: "workspace-a" });
  current = transitionTask(current, "preparing");
  current = transitionTask(current, "uploading", { uploadSessionId: "session-in-a" });
  current = transitionTask(current, "paused");
  current = transitionTask(current, "queued");
  current = transitionTask(current, "failed", { error: "Temporary failure" });
  current = retryTask(current);
  assert.equal(current.workspaceId, "workspace-a");
  current = transitionTask(transitionTask(current, "preparing"), "uploading");
  current = confirmTaskCompleted(current, true);
  assert.equal(current.workspaceId, "workspace-a");
});
