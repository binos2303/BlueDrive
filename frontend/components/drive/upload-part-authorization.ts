/**
 * Request expiring S3 multipart presigned URLs only when a transfer reaches a
 * bounded group of parts. A shared in-flight promise prevents several file
 * workers from issuing duplicate authorization requests for the same group.
 * URLs must never be persisted in localStorage or logging/diagnostics.
 */
export class OnDemandPartAuthorizer<T extends { part_number: number }> {
  private readonly indices = new Map<number, number>();
  private readonly batches = new Map<number, Promise<ReadonlyMap<number, T>>>();
  private readonly overrides = new Map<number, T>();
  private readonly pending: readonly number[];
  private readonly batchSize: number;
  private readonly authorizeBatch: (partNumbers: number[]) => Promise<readonly T[]>;

  constructor(
    pending: readonly number[],
    batchSize: number,
    authorizeBatch: (partNumbers: number[]) => Promise<readonly T[]>,
  ) {
    this.pending = pending;
    this.batchSize = batchSize;
    this.authorizeBatch = authorizeBatch;
    if (!Number.isSafeInteger(batchSize) || batchSize < 1 || batchSize > 1000) {
      throw new RangeError("Invalid multipart authorization batch size.");
    }
    pending.forEach((part, index) => {
      if (!Number.isSafeInteger(part) || part < 1 || this.indices.has(part)) {
        throw new RangeError("Multipart part numbers must be unique positive integers.");
      }
      this.indices.set(part, index);
    });
  }

  async get(partNumber: number, signal?: AbortSignal): Promise<T> {
    if (signal?.aborted) throw new DOMException("Upload interrupted.", "AbortError");
    const replacement = this.overrides.get(partNumber);
    if (replacement) return replacement;
    const index = this.indices.get(partNumber);
    if (index === undefined) throw new RangeError("Part is not pending in this upload.");
    const group = Math.floor(index / this.batchSize);
    let batch = this.batches.get(group);
    if (!batch) {
      const numbers = this.pending.slice(group * this.batchSize, (group + 1) * this.batchSize);
      batch = this.authorizeBatch([...numbers]).then((authorized) => {
        const result = new Map<number, T>();
        const expected = new Set(numbers);
        for (const part of authorized) {
          if (!expected.has(part.part_number) || result.has(part.part_number)) {
            throw new Error("Storage returned an unexpected or duplicated part authorization.");
          }
          result.set(part.part_number, part);
        }
        if (result.size !== numbers.length) throw new Error("Storage did not authorize all requested parts.");
        return result;
      }).catch((error: unknown) => {
        // A network failure should not permanently poison the group cache.
        this.batches.delete(group);
        throw error;
      });
      this.batches.set(group, batch);
    }
    const permission = (await batch).get(partNumber);
    if (signal?.aborted) throw new DOMException("Upload interrupted.", "AbortError");
    if (!permission) throw new Error("Part authorization is missing.");
    return this.overrides.get(partNumber) ?? permission;
  }

  /** A storage 403 may indicate an expired URL; refresh only that part. */
  replace(permission: T): void {
    if (!this.indices.has(permission.part_number)) throw new RangeError("Cannot replace a part outside this upload.");
    this.overrides.set(permission.part_number, permission);
  }
}
