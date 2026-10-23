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
import { CheckCircle2, ChevronDown, ChevronUp, CircleAlert, LoaderCircle, Pause, Play, RotateCcw, Upload, X } from "lucide-react";
import Button from "@/components/ui/Button";
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

import { DRIVE_UPLOAD_COMPLETED_EVENT } from "@/lib/workspace-context";
export { DRIVE_UPLOAD_COMPLETED_EVENT };

export type UploadFileInput = {
  file: File;
  relativePath: string;
  /** Optional per-file destination used when uploading a directory tree. */
  destinationId?: string | null;
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
const MAX_CONCURRENT_UPLOADS = 3;
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
  const [visible, setVisible] = useState(true);
  const [notification, setNotification] = useState<string | null>(null);
  const [dismissedTaskIds, setDismissedTaskIds] = useState<Set<string>>(() => new Set<string>());
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
    const incoming = inputs.map(({ file, relativePath, destinationId: fileDestinationId, validationError }) => {
      const id = `upload-${Date.now()}-${++nextId.current}`;
      if (!validationError) filesRef.current.set(id, file);
      return createUploadTask({
        id,
        fileName: file.name,
        relativePath,
        mimeType: file.type || "Unknown file type",
        size: file.size,
        destinationId: fileDestinationId !== undefined ? fileDestinationId : destinationId,
        validationError,
      });
    });
    setDismissedTaskIds((current) => {
      const next = new Set(current);
      incoming.forEach((task) => next.delete(task.id));
      return next;
    });
    commit((current) => markDuplicateTasks([...current, ...incoming]));
    setVisible(true);
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
            if (typeof window !== "undefined") {
              window.dispatchEvent(new CustomEvent(DRIVE_UPLOAD_COMPLETED_EVENT, {
                detail: { destinationId: latest.destinationId },
              }));
            }
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
    if (!current || ["completed", "failed", "canceled"].includes(current.status)) return;
    controllersRef.current.get(id)?.abort();
    updateTask(id, (task) => transitionTask(task, "canceled"));
    filesRef.current.delete(id);
    controllersRef.current.delete(id);
  }, [updateTask]);

  const closeManager = useCallback(() => {
    setDismissedTaskIds(new Set(tasksRef.current.map((task) => task.id)));
    setVisible(false);
  }, []);

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

  // Start selected files automatically, but bound concurrent files to avoid
  // launching hundreds of transfers when a folder contains many files.
  useEffect(() => {
    if (!service.connected) return;

    const activeIds = new Set(
      tasks
        .filter((task) => ["preparing", "uploading", "paused", "verifying", "scanning"].includes(task.status))
        .map((task) => task.id),
    );
    for (const id of controllersRef.current.keys()) activeIds.add(id);

    const freeSlots = MAX_CONCURRENT_UPLOADS - activeIds.size;
    if (freeSlots <= 0) return;

    const startable = tasks.filter((task) =>
      task.status === "queued"
      && (!task.duplicate || Boolean(task.conflictResolution))
      && !controllersRef.current.has(task.id),
    );
    for (const task of startable.slice(0, freeSlots)) {
      start(task.id);
    }
  }, [service.connected, start, tasks]);

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
    openManager: () => {
      setVisible(true);
      setOpen(true);
    },
  }), [enqueue, service.connected, service.supportsPauseResume, tasks]);


  const visibleTasks = tasks.filter((task) => !dismissedTaskIds.has(task.id));
  const queuedCount = visibleTasks.filter((task) => task.status === "queued").length;
  const activeCount = visibleTasks.filter((task) =>
    ["preparing", "uploading", "paused", "verifying", "scanning"].includes(task.status),
  ).length;
  const completedCount = visibleTasks.filter((task) => task.status === "completed").length;
  const failedCount = visibleTasks.filter((task) => task.status === "failed").length;

  const visibleCount = queuedCount + activeCount;
  const cancellableCount = visibleTasks.filter((task) =>
    ["queued", "preparing", "uploading", "paused", "verifying", "scanning"].includes(task.status),
  ).length;
  const etaSeconds = visibleTasks
    .filter((task) => task.status === "uploading" && Number.isFinite(task.progress?.etaSeconds))
    .map((task) => task.progress?.etaSeconds ?? 0)
    .filter((seconds) => seconds > 0);
  const etaLabel = etaSeconds.length
    ? `About ${formatDuration(Math.max(...etaSeconds))} remaining…`
    : activeCount > 0
      ? (visibleTasks.some((task) => task.status === "verifying" || task.status === "scanning")
        ? "Verifying upload…"
        : visibleTasks.some((task) => task.status === "preparing")
          ? "Starting upload…"
          : "Uploading…")
      : failedCount > 0
        ? `${failedCount} failed`
        : `${completedCount} completed`;
  const trayTitle = visibleCount > 0
    ? `Uploading ${visibleCount} item${visibleCount === 1 ? "" : "s"}`
    : completedCount > 0
      ? `Uploaded ${completedCount} item${completedCount === 1 ? "" : "s"}`
      : "Uploads";

  return (
    <UploadManagerContext.Provider value={contextValue}>
      {children}
      {visibleTasks.length > 0 && (
        visible ? (
          <section
            aria-label="Upload status"
            className="fixed bottom-0 right-0 z-80 flex max-h-[min(65vh,30rem)] w-[min(25rem,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-xl border border-border bg-background font-sans shadow-(--shadow-popover)"
          >
            <div className="flex min-h-12 items-center gap-2 border-b border-border bg-surface px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-semibold text-foreground">{trayTitle}</p>
              </div>
              <button
                type="button"
                onClick={() => setOpen((current) => !current)}
                aria-label={open ? "Collapse upload status" : "Expand upload status"}
                title={open ? "Collapse" : "Expand"}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-background"
              >
                {open ? <ChevronDown size={22} /> : <ChevronUp size={22} />}
              </button>
              <button
                type="button"
                onClick={closeManager}
                aria-label="Close and clear upload status"
                title="Hide"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-background"
              >
                <X size={21} />
              </button>
            </div>

            {open && (
              <>
            {activeCount > 0 && (
              <div className="flex min-h-8 items-center justify-between gap-2 border-b border-border bg-surface px-3 py-1.5">
                <p className="min-w-0 flex-1 truncate text-[12px] text-muted" role="status">
                  {visibleTasks.some((task) => task.status === "verifying" || task.status === "scanning")
                    ? "Processing upload…"
                    : etaLabel}
                </p>
                {cancellableCount > 0 && (
                  <span
                    className="flex h-8 w-8 shrink-0 items-center justify-center text-muted"
                    role="status"
                    aria-label="Upload in progress"
                    title="Upload in progress"
                  >
                    <LoaderCircle size={19} className="animate-spin" aria-hidden="true" />
                  </span>
                )}
              </div>
            )}
            {notification && (
              <div className="px-3 pt-3">
                <Toast title="Upload notice" variant="warning" onDismiss={() => setNotification(null)}>
                  {notification}
                </Toast>
              </div>
            )}

            {!service.connected && (
              <p className="border-b border-border px-4 py-2 text-xs text-warning" role="status">
                Upload service is not connected.
              </p>
            )}

            <ul aria-label="Upload items" className="min-h-0 space-y-0 overflow-y-auto">
              {visibleTasks.map((task) => (
                <UploadTaskRow
                  key={task.id}
                  task={task}
                  connected={service.connected}
                  canPause={service.supportsPauseResume && Boolean(task.uploadSessionId)}
                  onCancel={() => cancel(task.id)}
                  onRetry={() => retry(task.id)}
                  onPause={() => { void pause(task.id); }}
                  onResume={() => { void resume(task.id); }}
                  onConflictResolution={(value) => setConflictResolution(task.id, value)}
                />
              ))}
            </ul>

              </>
            )}
          </section>
        ) : (
          <button
            type="button"
            onClick={() => { setVisible(true); setOpen(true); }}
            aria-label={`Show upload status: ${queuedCount} queued, ${activeCount} in progress, ${completedCount} completed, ${failedCount} failed`}
            className="fixed bottom-0 right-0 z-80 inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-background px-4 text-sm font-semibold text-foreground shadow-(--shadow-popover) transition-colors hover:bg-surface"
          >
            {visibleCount > 0 ? <Upload size={17} aria-hidden="true" /> : <CheckCircle2 size={17} className="text-success" aria-hidden="true" />}
            {visibleCount > 0
              ? `Uploading ${visibleCount}`
              : completedCount > 0
                ? `Uploaded ${completedCount}`
                : `Uploads (${tasks.length})`}
            {activeCount > 0 && <span className="rounded-full bg-brand-soft px-2 py-0.5 text-xs text-brand-contrast">{activeCount}</span>}
          </button>
        )
      )}
    </UploadManagerContext.Provider>
  );
}

function UploadTaskRow({
  task,
  connected,
  canPause,
  onCancel,
  onRetry,
  onPause,
  onResume,
  onConflictResolution,
}: {
  task: UploadTask;
  connected: boolean;
  canPause: boolean;
  onCancel: () => void;
  onRetry: () => void;
  onPause: () => void;
  onResume: () => void;
  onConflictResolution: (value: UploadConflictResolution) => void;
}) {
  const terminal = task.status === "completed" || task.status === "failed" || task.status === "canceled";
  const canCancel = ["queued", "preparing", "uploading", "paused", "verifying", "scanning"].includes(task.status);
  const showProgress = Boolean(task.progress)
    && ["uploading", "verifying", "scanning"].includes(task.status);
  const transferred = task.progress?.uploadedBytes ?? 0;
  const total = task.progress?.totalBytes ?? task.size;
  const progressPercent = total > 0 ? Math.min(100, Math.round((transferred / total) * 100)) : 0;

  return (
    <li className="border-b border-border px-3 py-2 last:border-b-0">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface text-muted">
          <Upload size={17} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium text-foreground" title={task.fileName}>{task.fileName}</p>
          <p className="truncate text-[11px] text-muted" title={task.relativePath}>
            {task.relativePath === task.fileName ? formatBytes(task.size) : `${task.relativePath} · ${formatBytes(task.size)}`}
          </p>
        </div>

        {task.status === "completed" ? (
          <CheckCircle2 size={21} aria-label="Upload completed" className="shrink-0 text-success" />
        ) : task.status === "failed" ? (
          <CircleAlert size={21} aria-label="Upload failed" className="shrink-0 text-danger" />
        ) : task.status === "canceled" ? (
          <X size={19} aria-label="Upload canceled" className="shrink-0 text-muted" />
        ) : canCancel ? (
          <button
            type="button"
            onClick={onCancel}
            aria-label={`Stop upload of ${task.fileName}`}
            title="Stop upload"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface hover:text-foreground"
          >
            <X size={18} />
          </button>
        ) : !terminal ? (
          <LoaderCircle
            size={22}
            aria-label={`Upload ${statusLabel(task.status).toLowerCase()}`}
            className="shrink-0 animate-spin text-muted"
          />
        ) : null}
      </div>

      {!terminal && task.status !== "verifying" && task.status !== "scanning" && (
        <p className="mt-1 text-[11px] text-muted">
          {task.status === "uploading" && task.progress
            ? `${progressPercent}% uploaded`
            : statusLabel(task.status)}
        </p>
      )}

      {showProgress && task.status === "uploading" && (
        <div className="mt-2">
          <progress
            aria-label={`Upload progress for ${task.fileName}`}
            max={Math.max(total, 1)}
            value={Math.min(transferred, total)}
            className="h-1.5 w-full overflow-hidden rounded-full accent-success"
          />
        </div>
      )}

      {task.status === "failed" && (
        <div className="mt-2 flex items-start justify-between gap-2">
          <p role="alert" className="min-w-0 text-xs text-danger">
            {task.error}
            {task.retryPolicy.retryable && <span> Retry {task.retryPolicy.retries}/{task.retryPolicy.maxRetries}.</span>}
          </p>
          {task.retryPolicy.retryable && (
            <Button
              size="sm"
              variant="secondary"
              onClick={onRetry}
              disabled={!connected || task.retryPolicy.retries >= task.retryPolicy.maxRetries}
              aria-label={`Retry ${task.fileName}`}
            >
              <RotateCcw size={13} /> Retry
            </Button>
          )}
        </div>
      )}

      {task.duplicate && !terminal && (
        <fieldset className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-2 text-xs text-warning">
          <legend className="px-1 font-medium">Duplicate path</legend>
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
        </fieldset>
      )}

      {canPause && task.status === "uploading" && (
        <button type="button" onClick={onPause} className="mt-2 text-xs text-muted underline" aria-label={`Pause ${task.fileName}`}>
          <Pause size={12} className="mr-1 inline" />Pause
        </button>
      )}
      {canPause && task.status === "paused" && (
        <button type="button" onClick={onResume} className="mt-2 text-xs text-muted underline" aria-label={`Resume ${task.fileName}`}>
          <Play size={12} className="mr-1 inline" />Resume
        </button>
      )}
      {task.status === "queued" && !task.duplicate && !connected && (
        <p className="mt-2 text-xs text-warning">Upload service is not connected.</p>
      )}
      {task.status === "queued" && task.duplicate && !task.conflictResolution && (
        <p className="mt-2 text-xs text-warning">Choose how to handle this duplicate to continue.</p>
      )}
    </li>
  );
}
