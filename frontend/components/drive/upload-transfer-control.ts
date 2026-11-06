/**
 * A pause interrupts browser PUT requests but keeps the provider's multipart
 * upload session alive. Cancellation is a separate signal from UploadManager.
 */
export class UploadPausedError extends Error {
  constructor() {
    super("Upload paused; completed parts remain available for resume.");
    this.name = "UploadPausedError";
  }
}

export class UploadTransferControl {
  private readonly controller = new AbortController();
  private readonly externalSignal: AbortSignal;
  private pauseRequested = false;
  private finishWaiting!: () => void;
  private disposed = false;
  readonly finished: Promise<void>;

  private readonly onCancel = () => this.controller.abort();

  constructor(cancelSignal: AbortSignal) {
    this.externalSignal = cancelSignal;
    this.finished = new Promise<void>((resolve) => { this.finishWaiting = resolve; });
    if (cancelSignal.aborted) this.onCancel();
    else cancelSignal.addEventListener("abort", this.onCancel, { once: true });
  }

  get signal(): AbortSignal { return this.controller.signal; }
  get paused(): boolean { return this.pauseRequested && !this.externalSignal.aborted; }

  pause(): void {
    if (this.disposed || this.externalSignal.aborted) throw new Error("Upload is no longer pausable.");
    this.pauseRequested = true;
    this.controller.abort();
  }

  throwIfPaused(): void {
    if (this.paused) throw new UploadPausedError();
  }

  finish(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.externalSignal.removeEventListener("abort", this.onCancel);
    this.finishWaiting();
  }
}
