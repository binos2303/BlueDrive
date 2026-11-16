/** Constant-time accounting of transport bytes for concurrent multipart PUTs. */
export class UploadPartProgress {
  private readonly loaded = new Map<number, number>();
  private transferred = 0;
  private readonly fileSize: number;
  private readonly partSize: number;

  constructor(fileSize: number, partSize: number) {
    this.fileSize = fileSize;
    this.partSize = partSize;
    if (!Number.isSafeInteger(fileSize) || fileSize < 0 || !Number.isSafeInteger(partSize) || partSize <= 0) {
      throw new RangeError("Invalid multipart file or part size.");
    }
  }

  get uploadedBytes(): number { return this.transferred; }

  update(partNumber: number, loaded: number): number {
    const start = (partNumber - 1) * this.partSize;
    if (!Number.isSafeInteger(partNumber) || partNumber < 1 || start >= this.fileSize) {
      throw new RangeError("Invalid part number for this file.");
    }
    const max = Math.min(this.partSize, this.fileSize - start);
    const safe = Number.isFinite(loaded) ? Math.max(0, Math.min(loaded, max)) : 0;
    const previous = this.loaded.get(partNumber) ?? 0;
    this.transferred += safe - previous;
    this.loaded.set(partNumber, safe);
    return this.transferred;
  }
}
