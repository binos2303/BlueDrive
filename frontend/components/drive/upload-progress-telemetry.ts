/**
 * Sample high-frequency XHR progress at a bounded cadence instead of causing
 * one React state update per transport event. Throughput uses NET progress,
 * not the already-received parts restored during Resume.
 */
export type UploadTelemetrySnapshot = {
  uploadedBytes: number;
  totalBytes: number;
  bytesPerSecond?: number;
  etaSeconds?: number;
};

type Sample = { at: number; bytes: number };

export class UploadProgressTelemetry {
  private readonly samples: Sample[];
  private lastSeenBytes: number;
  private lastEmittedAt = Number.NEGATIVE_INFINITY;
  private lastAt: number;
  private readonly totalBytes: number;
  private readonly clock: () => number;
  private readonly minUpdateMs: number;
  private readonly windowMs: number;

  constructor(
    totalBytes: number,
    initialBytes = 0,
    clock: () => number = () => performance.now(),
    minUpdateMs = 150,
    windowMs = 5000,
  ) {
    this.totalBytes = totalBytes;
    this.clock = clock;
    this.minUpdateMs = minUpdateMs;
    this.windowMs = windowMs;
    if (!Number.isSafeInteger(totalBytes) || totalBytes < 0 ||
        !Number.isSafeInteger(initialBytes) || initialBytes < 0 || initialBytes > totalBytes ||
        !Number.isFinite(minUpdateMs) || minUpdateMs < 0 ||
        !Number.isFinite(windowMs) || windowMs <= minUpdateMs) {
      throw new RangeError("Invalid upload telemetry configuration.");
    }
    this.lastSeenBytes = initialBytes;
    this.lastAt = this.clock();
    this.samples = [{ at: this.lastAt, bytes: initialBytes }];
  }

  report(bytes: number, force = false): UploadTelemetrySnapshot | null {
    const now = Math.max(this.lastAt, this.clock());
    this.lastAt = now;
    const safe = Number.isFinite(bytes) ? Math.max(0, Math.min(bytes, this.totalBytes)) : this.lastSeenBytes;
    const rolledBack = safe < this.lastSeenBytes;
    this.lastSeenBytes = safe;
    if (rolledBack) {
      // A retry can reset one part's progress to zero. Old samples would
      // otherwise produce negative speeds or misleading ETAs.
      this.samples.length = 0;
      this.samples.push({ at: now, bytes: safe });
    }
    if (!force && !rolledBack && now - this.lastEmittedAt < this.minUpdateMs) return null;
    this.lastEmittedAt = now;
    if (!rolledBack) this.samples.push({ at: now, bytes: safe });
    while (this.samples.length > 1 && this.samples[1].at <= now - this.windowMs) this.samples.shift();

    const first = this.samples[0];
    const elapsed = (now - first.at) / 1000;
    const delta = safe - first.bytes;
    const snapshot: UploadTelemetrySnapshot = { uploadedBytes: safe, totalBytes: this.totalBytes };
    if (elapsed >= 0.25 && delta > 0) {
      const speed = delta / elapsed;
      if (Number.isFinite(speed) && speed > 0) {
        snapshot.bytesPerSecond = speed;
        snapshot.etaSeconds = Math.max(0, (this.totalBytes - safe) / speed);
      }
    }
    return snapshot;
  }
}
