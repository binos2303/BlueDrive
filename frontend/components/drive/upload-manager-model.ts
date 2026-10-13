export type UploadStatus =
  | "queued"
  | "preparing"
  | "uploading"
  | "paused"
  | "verifying"
  | "scanning"
  | "completed"
  | "failed"
  | "canceled";

export type RetryPolicy = {
  retries: number;
  maxRetries: number;
  retryable: boolean;
};

export type UploadProgress = {
  uploadedBytes: number;
  totalBytes: number;
  bytesPerSecond?: number;
  etaSeconds?: number;
};

export type UploadTask = {
  id: string;
  fileName: string;
  relativePath: string;
  mimeType: string;
  size: number;
  destinationId: string | null;
  status: UploadStatus;
  retryPolicy: RetryPolicy;
  error: string | null;
  progress: UploadProgress | null;
  uploadSessionId: string | null;
  duplicate: boolean;
  conflictResolution: "reject" | "skip" | "keep-both" | "replace" | null;
};

const transitions: Record<UploadStatus, readonly UploadStatus[]> = {
  queued: ["preparing", "canceled", "failed"],
  preparing: ["uploading", "failed", "canceled"],
  uploading: ["paused", "verifying", "scanning", "completed", "failed", "canceled"],
  paused: ["uploading", "failed", "canceled"],
  verifying: ["scanning", "completed", "failed", "canceled"],
  scanning: ["completed", "failed", "canceled"],
  completed: [],
  failed: ["queued", "canceled"],
  canceled: [],
};

export function canTransition(from: UploadStatus, to: UploadStatus): boolean {
  return transitions[from].includes(to);
}

export function transitionTask(
  task: UploadTask,
  nextStatus: UploadStatus,
  patch: Partial<Pick<UploadTask, "error" | "progress" | "uploadSessionId" | "retryPolicy">> = {},
): UploadTask {
  if (nextStatus === "completed") {
    throw new Error("Use confirmTaskCompleted only after the upload service confirms completion and required checks.");
  }
  return applyTransition(task, nextStatus, patch);
}

function applyTransition(
  task: UploadTask,
  nextStatus: UploadStatus,
  patch: Partial<Pick<UploadTask, "error" | "progress" | "uploadSessionId" | "retryPolicy">>,
): UploadTask {
  if (!canTransition(task.status, nextStatus)) {
    throw new Error(`Invalid upload transition: ${task.status} -> ${nextStatus}`);
  }
  return {
    ...task,
    ...patch,
    status: nextStatus,
    error: nextStatus === "failed" ? (patch.error ?? task.error) : null,
  };
}

export function confirmTaskCompleted(task: UploadTask, backendConfirmed: boolean): UploadTask {
  if (!backendConfirmed) {
    throw new Error("Upload completion requires backend confirmation and all required checks.");
  }
  return applyTransition(task, "completed", {});
}

export function retryTask(task: UploadTask, maxRetries = task.retryPolicy.maxRetries): UploadTask {
  if (task.status !== "failed") {
    throw new Error(`Only failed uploads can be retried (current status: ${task.status}).`);
  }
  if (!task.retryPolicy.retryable) {
    throw new Error(task.error ?? "This upload cannot be retried. Check the error guidance.");
  }
  if (task.retryPolicy.retries >= maxRetries) {
    throw new Error(`Retry limit reached (${maxRetries}). Choose a corrective action before trying again.`);
  }
  return transitionTask(task, "queued", {
    error: null,
    progress: null,
    retryPolicy: { ...task.retryPolicy, retries: task.retryPolicy.retries + 1 },
  });
}

export function createUploadTask(input: {
  id: string;
  fileName: string;
  relativePath: string;
  mimeType: string;
  size: number;
  destinationId: string | null;
  validationError?: string | null;
}): UploadTask {
  const { validationError, ...taskInput } = input;
  const task: UploadTask = {
    ...taskInput,
    status: "queued",
    retryPolicy: { retries: 0, maxRetries: 3, retryable: true },
    error: null,
    progress: null,
    uploadSessionId: null,
    duplicate: false,
    conflictResolution: null,
  };
  return validationError
    ? transitionTask(task, "failed", {
        error: validationError,
        retryPolicy: { retries: 0, maxRetries: 3, retryable: false },
      })
    : task;
}

export function markDuplicateTasks(tasks: UploadTask[]): UploadTask[] {
  const counts = new Map<string, number>();
  for (const task of tasks) {
    if (task.status === "canceled" || (task.status === "failed" && !task.retryPolicy.retryable)) continue;
    const key = `${task.destinationId ?? "root"}:${task.relativePath.toLocaleLowerCase()}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return tasks.map((task) => ({
    ...task,
    duplicate: task.status !== "canceled"
      && !(task.status === "failed" && !task.retryPolicy.retryable)
      && (counts.get(`${task.destinationId ?? "root"}:${task.relativePath.toLocaleLowerCase()}`) ?? 0) > 1,
    conflictResolution: task.status !== "canceled"
      && !(task.status === "failed" && !task.retryPolicy.retryable)
      && (counts.get(`${task.destinationId ?? "root"}:${task.relativePath.toLocaleLowerCase()}`) ?? 0) > 1
      ? task.conflictResolution
      : null,
  }));
}
