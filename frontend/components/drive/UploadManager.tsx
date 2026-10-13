"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle2, CircleAlert, Pause, Play, RotateCcw, Upload, X } from "lucide-react";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";
import Toast from "@/components/ui/Toast";
import {
  createUploadTask,
  confirmTaskCompleted,
  markDuplicateTasks,
  retryTask,
  transitionTask,
  type UploadStatus,
  type UploadTask,
} from "./upload-manager-model";
import {
  djangoMultipartUploadService,
  UploadServiceUnavailableError,
  type UploadFailure,
  type UploadProgressReport,
  type UploadService,
} from "./upload-service";

export type UploadFileInput = {
  file: File;
  relativePath: string;
  validationError?: string | null;
};

type UploadConflictResolution = NonNullable<UploadTask["conflictResolution"]>;

type UploadManagerValue = {
  tasks: UploadTask[];
  serviceConnected: boolean;
  supportsPauseResume: boolean;
  enqueue: (files: readonly UploadFileInput[], destinationId: string | null) => void;
  openManager: () => void;
};

const UploadManagerContext = createContext<UploadManagerValue | null>(null);

const MAX_RETRIES = 3;
const ACTIVE_STATUSES: UploadStatus[] = [
  "queued", "preparing", "uploading", "paused", "verifying", "scanning",
];

function isActive(task: UploadTask): boolean {
  return ACTIVE_STATUSES.includes(task.status);
}

function statusLabel(status: UploadStatus): string {
  return {
    queued: "Queued",
    preparing: "Preparing",
    uploading: "Uploading",
    paused: "Paused",
    verifying: "Verifying",
    scanning: "Scanning",
    completed: "Completed",
    failed: "Failed",
    canceled: "Canceled",
  }[status];
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; value >= 1024 && index < units.length; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${unit}`;
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const rounded = Math.ceil(seconds);
  if (rounded < 60) return `${rounded}s`;
  if (rounded < 3600) return `${Math.ceil(rounded / 60)}m`;
  return `${Math.floor(rounded / 3600)}h ${Math.ceil((rounded % 3600) / 60)}m`;
}

export function useUploadManager(): UploadManagerValue {
  const context = useContext(UploadManagerContext);
  if (!context) throw new Error("useUploadManager must be used inside UploadManager.");
  return context;
}

export default function UploadManager({
  children,
  service = djangoMultipartUploadService,
}: {
  children: ReactNode;
  service?: UploadService;
}) {
  const [tasks, setTasks] = useState<UploadTask[]>([]);
  const [open, setOpen] = useState(false);
  const [notification, setNotification] = useState<string | null>(null);
  const tasksRef = useRef(tasks);
  const filesRef = useRef(new Map<string, File>());
  const controllersRef = useRef(new Map<string, AbortController>());
  const nextId = useRef(0);

  const commit = useCallback((update: (current: UploadTask[]) => UploadTask[]) => {
    const next = markDuplicateTasks(update(tasksRef.current));
    tasksRef.current = next;
    setTasks(next);
  }, []);

  const updateTask = useCallback((id: string, update: (task: UploadTask) => UploadTask) => {
    commit((current) => current.map((task) => task.id === id ? update(task) : task));
  }, [commit]);

  const enqueue = useCallback((inputs: readonly UploadFileInput[], destinationId: string | null) => {
    const incoming = inputs.map(({ file, relativePath, validationError }) => {
      const id = `upload-${Date.now()}-${++nextId.current}`;
      if (!validationError) filesRef.current.set(id, file);
      return createUploadTask({
        id,
        fileName: file.name,
        relativePath,
        mimeType: file.type || "Unknown file type",
        size: file.size,
        destinationId,
        validationError,
      });
    });
    commit((current) => markDuplicateTasks([...current, ...incoming]));
    setOpen(true);
  }, [commit]);

  const applyFailure = useCallback((id: string, failure: UploadFailure) => {
    const current = tasksRef.current.find((task) => task.id === id);
    if (!current || !isActive(current)) return;
    const retryable = failure.retryable && current.retryPolicy.retries < MAX_RETRIES;
    if (!retryable) filesRef.current.delete(id);
    updateTask(id, (task) => transitionTask(task, "failed", {
      error: [failure.message, failure.action].filter(Boolean).join(" "),
      retryPolicy: {
        ...task.retryPolicy,
        maxRetries: MAX_RETRIES,
        retryable,
      },
    }));
  }, [updateTask]);

  const run = useCallback(async (id: string) => {
    const current = tasksRef.current.find((task) => task.id === id);
    const file = filesRef.current.get(id);
    if (!current || current.status !== "queued" || controllersRef.current.has(id) || !service.connected) return;
    if (current.duplicate && !current.conflictResolution) return;
    if (!file) {
      applyFailure(id, {
        message: "The in-memory file is no longer available.",
        retryable: false,
        action: "Select the file again.",
      });
      return;
    }

    const controller = new AbortController();
    controllersRef.current.set(id, controller);
    let backendConfirmedComplete = false;
    try {
      await service.upload(
        tasksRef.current.find((task) => task.id === id)!,
        file,
        {
          onStatus: (status, uploadSessionId) => {
            const latest = tasksRef.current.find((task) => task.id === id);
            if (!latest || !isActive(latest)) return;
            if (latest.status === status) {
              if (uploadSessionId && uploadSessionId !== latest.uploadSessionId) {
                updateTask(id, (task) => ({ ...task, uploadSessionId }));
              }
              return;
            }
            try {
              updateTask(id, (task) => transitionTask(task, status, {
                uploadSessionId: uploadSessionId ?? task.uploadSessionId,
              }));
            } catch {
              applyFailure(id, {
                message: `Upload service reported an unexpected state (${status}).`,
                retryable: false,
                action: "Contact support before retrying.",
              });
            }
          },
          onProgress: (progress: UploadProgressReport) => {
            const latest = tasksRef.current.find((task) => task.id === id);
            if (!latest || latest.status !== "uploading") return;
            const totalBytes = Number.isFinite(progress.totalBytes) && progress.totalBytes >= 0
              ? progress.totalBytes
              : latest.size;
            const uploadedBytes = Number.isFinite(progress.uploadedBytes)
              ? Math.max(0, Math.min(progress.uploadedBytes, totalBytes))
              : 0;
            updateTask(id, (task) => ({
              ...task,
              progress: {
                uploadedBytes,
                totalBytes,
                ...(Number.isFinite(progress.bytesPerSecond) && (progress.bytesPerSecond ?? 0) > 0
                  ? { bytesPerSecond: progress.bytesPerSecond }
                  : {}),
                ...(Number.isFinite(progress.etaSeconds) && (progress.etaSeconds ?? -1) >= 0
                  ? { etaSeconds: progress.etaSeconds }
                  : {}),
              },
            }));
          },
          onCompleted: () => {
            const latest = tasksRef.current.find((task) => task.id === id);
            if (!latest || !isActive(latest) || latest.status === "queued" || latest.status === "preparing") return;
            updateTask(id, (task) => confirmTaskCompleted(task, true));
            backendConfirmedComplete = true;
            filesRef.current.delete(id);
          },
        },
        controller.signal,
      );
      const latest = tasksRef.current.find((task) => task.id === id);
      if (latest?.status === "canceled") return;
      if (!backendConfirmedComplete) {
        applyFailure(id, {
          message: "Upload service ended without confirming object completion and required checks.",
          retryable: false,
          action: "Do not treat this file as available. Check service logs or contact support.",
        });
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof UploadServiceUnavailableError) {
        applyFailure(id, { message: error.message, retryable: false, action: error.action });
      } else {
        const reported = error as Partial<UploadFailure>;
        applyFailure(id, {
          message: typeof reported.message === "string" ? reported.message : "Upload failed unexpectedly.",
          retryable: reported.retryable === true,
          action: typeof reported.action === "string" ? reported.action : "Review the error before retrying.",
        });
      }
    } finally {
      controllersRef.current.delete(id);
    }
  }, [applyFailure, service, updateTask]);

  const start = useCallback((id: string) => {
    void run(id);
  }, [run]);

  const retry = useCallback((id: string) => {
    try {
      updateTask(id, (task) => retryTask(task, MAX_RETRIES));
      start(id);
    } catch (error) {
      setNotification(error instanceof Error ? error.message : "This upload cannot be retried.");
    }
  }, [start, updateTask]);

  const cancel = useCallback((id: string) => {
    const current = tasksRef.current.find((task) => task.id === id);
    if (!current || current.status === "completed" || current.status === "canceled") return;
    controllersRef.current.get(id)?.abort();
    updateTask(id, (task) => transitionTask(task, "canceled"));
    filesRef.current.delete(id);
    controllersRef.current.delete(id);
  }, [updateTask]);

  const setConflictResolution = useCallback((id: string, value: UploadConflictResolution) => {
    updateTask(id, (task) => ({ ...task, conflictResolution: value }));
  }, [updateTask]);

  const pause = useCallback(async (id: string) => {
    const task = tasksRef.current.find((item) => item.id === id);
    if (!task || !service.supportsPauseResume || !service.pause || task.status !== "uploading" || !task.uploadSessionId) return;
    try {
      await service.pause(task);
      const latest = tasksRef.current.find((item) => item.id === id);
      if (latest?.status === "uploading") updateTask(id, (item) => transitionTask(item, "paused"));
    } catch (error) {
      setNotification(error instanceof Error ? error.message : "The upload could not be paused.");
    }
  }, [service, updateTask]);

  const resume = useCallback(async (id: string) => {
    const task = tasksRef.current.find((item) => item.id === id);
    if (!task || !service.supportsPauseResume || !service.resume || task.status !== "paused" || !task.uploadSessionId) return;
    try {
      await service.resume(task);
      const latest = tasksRef.current.find((item) => item.id === id);
      if (latest?.status === "paused") updateTask(id, (item) => transitionTask(item, "uploading"));
    } catch (error) {
      setNotification(error instanceof Error ? error.message : "The upload could not be resumed.");
    }
  }, [service, updateTask]);

  const clearFinished = useCallback(() => {
    commit((current) => {
      const retained = current.filter((task) => isActive(task));
      const retainedIds = new Set(retained.map((task) => task.id));
      for (const task of current) {
        if (!retainedIds.has(task.id)) filesRef.current.delete(task.id);
      }
      return markDuplicateTasks(retained);
    });
  }, [commit]);

  useEffect(() => {
    function warnBeforeUnload(event: BeforeUnloadEvent) {
      if (!tasksRef.current.some(isActive)) return;
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, []);

  useEffect(() => () => {
    controllersRef.current.forEach((controller) => controller.abort());
    controllersRef.current.clear();
    filesRef.current.clear();
  }, []);

  const contextValue = useMemo<UploadManagerValue>(() => ({
    tasks,
    serviceConnected: service.connected,
    supportsPauseResume: service.supportsPauseResume,
    enqueue,
    openManager: () => setOpen(true),
  }), [enqueue, service.connected, service.supportsPauseResume, tasks]);

  const groupedProgress = useMemo(() => {
    const measured = tasks.some((task) => task.progress !== null);
    if (!measured) return null;
    const total = tasks.reduce((sum, task) => sum + task.size, 0);
    if (total <= 0) return null;
    const uploaded = tasks.reduce((sum, task) => {
      if (task.status === "completed") return sum + task.size;
      return sum + (task.progress?.uploadedBytes ?? 0);
    }, 0);
    return { total, uploaded: Math.min(uploaded, total) };
  }, [tasks]);
  const queuedCount = tasks.filter((task) => task.status === "queued").length;
  const activeCount = tasks.filter((task) =>
    ["preparing", "uploading", "paused", "verifying", "scanning"].includes(task.status),
  ).length;
  const completedCount = tasks.filter((task) => task.status === "completed").length;
  const failedCount = tasks.filter((task) => task.status === "failed").length;

  return (
    <UploadManagerContext.Provider value={contextValue}>
      {children}
      {tasks.length > 0 && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label={`Open upload manager: ${queuedCount} queued, ${activeCount} in progress, ${completedCount} completed, ${failedCount} failed`}
          className="fixed bottom-4 right-4 z-[60] inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-surface px-4 text-sm font-semibold text-foreground shadow-[var(--shadow-popover)] transition-colors hover:bg-background"
        >
          <Upload size={17} aria-hidden="true" />
          Uploads
          {activeCount > 0 && <span className="rounded-full bg-brand-soft px-2 py-0.5 text-xs text-brand-contrast">{activeCount}</span>}
        </button>
      )}
      <Dialog
        open={open}
        title="Upload manager"
        description="This queue stays available while navigating within the app. It is held in memory only and will be lost on refresh or tab close."
        onClose={() => setOpen(false)}
        className="max-h-[min(90vh,52rem)] w-[min(100%-2rem,54rem)]"
      >
        <div className="space-y-4">
          {notification && (
            <Toast title="Upload manager" variant="warning" onDismiss={() => setNotification(null)}>
              {notification}
            </Toast>
          )}
          <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-warning">
            Refreshing or closing this tab discards the in-memory queue and file handles. Active transfers may stop. This service does not support resumable uploads.
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted">
            <span role="status" aria-live="polite">{queuedCount} queued · {activeCount} in progress · {completedCount} completed · {failedCount} failed</span>
            {!service.connected && <span className="font-medium text-warning">Upload service not connected</span>}
          </div>
          {groupedProgress && (
            <div className="space-y-1" aria-label="Measured aggregate upload progress">
              <div className="flex justify-between text-xs text-muted">
                <span>Measured transfer progress</span>
                <span>{formatBytes(groupedProgress.uploaded)} / {formatBytes(groupedProgress.total)}</span>
              </div>
              <progress
                aria-label="Aggregate bytes transferred"
                max={groupedProgress.total}
                value={groupedProgress.uploaded}
                className="h-2 w-full accent-brand-contrast"
              />
            </div>
          )}
          <ul aria-label="Upload items" className="max-h-[min(48vh,28rem)] space-y-2 overflow-y-auto">
            {tasks.map((task) => (
              <UploadTaskRow
                key={task.id}
                task={task}
                connected={service.connected}
                canPause={service.supportsPauseResume && Boolean(task.uploadSessionId)}
                onStart={() => start(task.id)}
                onCancel={() => cancel(task.id)}
                onRetry={() => retry(task.id)}
                onPause={() => { void pause(task.id); }}
                onResume={() => { void resume(task.id); }}
                onConflictResolution={(value) => setConflictResolution(task.id, value)}
              />
            ))}
          </ul>
          {tasks.length === 0 && (
            <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted">No uploads queued.</p>
          )}
          <div className="flex flex-wrap justify-between gap-2 border-t border-border pt-4">
            <Button variant="secondary" onClick={clearFinished} disabled={!tasks.some((task) => !isActive(task))}>
              Clear finished
            </Button>
            <div className="flex gap-2">
              {service.connected && (
                <Button
                  variant="secondary"
                  onClick={() => tasks.filter((task) => task.status === "queued").forEach((task) => start(task.id))}
                  disabled={!tasks.some((task) => task.status === "queued")}
                >
                  Start queued
                </Button>
              )}
              <Button variant="secondary" onClick={() => setOpen(false)}>Close</Button>
            </div>
          </div>
        </div>
      </Dialog>
    </UploadManagerContext.Provider>
  );
}

function UploadTaskRow({
  task,
  connected,
  canPause,
  onStart,
  onCancel,
  onRetry,
  onPause,
  onResume,
  onConflictResolution,
}: {
  task: UploadTask;
  connected: boolean;
  canPause: boolean;
  onStart: () => void;
  onCancel: () => void;
  onRetry: () => void;
  onPause: () => void;
  onResume: () => void;
  onConflictResolution: (value: UploadConflictResolution) => void;
}) {
  const terminal = task.status === "completed" || task.status === "failed" || task.status === "canceled";
  return (
    <li className="rounded-xl border border-border bg-background p-3">
      <div className="flex min-w-0 items-start gap-3">
        {task.status === "completed"
          ? <CheckCircle2 size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-success" />
          : task.status === "failed"
            ? <CircleAlert size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-danger" />
            : <Upload size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-brand-contrast" />}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground" title={task.fileName}>{task.fileName}</p>
          <p className="truncate text-xs text-muted" title={task.relativePath}>{task.relativePath} · {formatBytes(task.size)}</p>
          <p className={`mt-1 text-xs font-semibold ${task.status === "failed" ? "text-danger" : task.status === "completed" ? "text-success" : "text-muted"}`}>
            {statusLabel(task.status)}
          </p>
          {task.progress && task.status === "uploading" && (
            <div className="mt-2 space-y-1">
              <div className="flex justify-between text-xs text-muted">
                <span>{formatBytes(task.progress.uploadedBytes)} / {formatBytes(task.progress.totalBytes)}</span>
                {task.progress.bytesPerSecond !== undefined && (
                  <span>{formatBytes(task.progress.bytesPerSecond)}/s{task.progress.etaSeconds !== undefined ? ` · ${formatDuration(task.progress.etaSeconds)} left` : ""}</span>
                )}
              </div>
              <progress
                aria-label={`Transfer progress for ${task.fileName}`}
                max={Math.max(task.progress.totalBytes, 1)}
                value={Math.min(task.progress.uploadedBytes, task.progress.totalBytes)}
                className="h-2 w-full accent-brand-contrast"
              />
            </div>
          )}
          {task.error && (
            <p role="alert" className="mt-1 text-xs text-danger">
              {task.error}
              {task.retryPolicy.retryable && <span> Retry {task.retryPolicy.retries}/{task.retryPolicy.maxRetries}.</span>}
            </p>
          )}
          {task.duplicate && (
            <fieldset className="mt-2 rounded-lg border border-amber-300 bg-amber-50 p-2 text-xs text-warning">
              <legend className="px-1 font-medium">Duplicate path conflict</legend>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {([
                  ["skip", "Skip"],
                  ["keep-both", "Keep both"],
                  ["replace", "Replace"],
                ] as const).map(([value, label]) => (
                  <label key={value} className="inline-flex items-center gap-1">
                    <input
                      type="radio"
                      name={`conflict-${task.id}`}
                      checked={task.conflictResolution === value}
                      onChange={() => onConflictResolution(value)}
                    />
                    {label}
                  </label>
                ))}
              </div>
              <span className="block pt-1">Policy is passed to the service; the server must authorize and enforce it.</span>
            </fieldset>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1">
          {task.status === "queued" && (
            <Button size="sm" variant="secondary" onClick={onStart} disabled={!connected || (task.duplicate && !task.conflictResolution)}>
              Start
            </Button>
          )}
          {task.status === "failed" && task.retryPolicy.retryable && (
            <Button
              size="sm"
              variant="secondary"
              onClick={onRetry}
              disabled={!connected || task.retryPolicy.retries >= task.retryPolicy.maxRetries}
              aria-label={`Retry ${task.fileName}`}
            >
              <RotateCcw size={14} /> Retry
            </Button>
          )}
          {canPause && task.status === "uploading" && (
            <Button size="sm" variant="secondary" onClick={onPause} aria-label={`Pause ${task.fileName}`}>
              <Pause size={14} />
            </Button>
          )}
          {canPause && task.status === "paused" && (
            <Button size="sm" variant="secondary" onClick={onResume} aria-label={`Resume ${task.fileName}`}>
              <Play size={14} />
            </Button>
          )}
          {!terminal && (
            <Button size="sm" variant="ghost" onClick={onCancel} aria-label={`Cancel ${task.fileName}`}>
              <X size={14} /> Cancel
            </Button>
          )}
        </div>
      </div>
    </li>
  );
}
