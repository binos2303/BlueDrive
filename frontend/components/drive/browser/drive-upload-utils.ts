export const MAX_UPLOAD_FILES_PER_BATCH = 500;
const MAX_UPLOAD_FILE_SIZE = 100 * 1024 * 1024;
const MAX_UPLOAD_PATH_LENGTH = 1024;
const MAX_FILE_NAME_LENGTH = 255;

export type DroppedEntry = {
  name: string;
  fullPath: string;
  isFile: boolean;
  isDirectory: boolean;
  file?: (success: (file: File) => void, failure: (error: DOMException) => void) => void;
  createReader?: () => {
    readEntries: (
      success: (entries: DroppedEntry[]) => void,
      failure: (error: DOMException) => void,
    ) => void;
  };
};

export function getDroppedEntry(item: DataTransferItem): DroppedEntry | null {
  const itemWithEntry = item as DataTransferItem & {
    webkitGetAsEntry?: () => DroppedEntry | null;
  };
  return itemWithEntry.webkitGetAsEntry?.() ?? null;
}

export async function readDroppedEntry(entry: DroppedEntry): Promise<{ file: File; relativePath: string }[]> {
  if (entry.isFile && entry.file) {
    const file = await new Promise<File>((resolve, reject) => {
      entry.file?.(resolve, reject);
    });
    return [{ file, relativePath: entry.fullPath.replace(/^\/+/, "") || file.name }];
  }

  if (entry.isDirectory && entry.createReader) {
    const reader = entry.createReader();
    const children: DroppedEntry[] = [];
    while (true) {
      const batch = await new Promise<DroppedEntry[]>((resolve, reject) => {
        reader.readEntries(resolve, reject);
      });
      if (batch.length === 0) break;
      children.push(...batch);
    }
    const nested = await Promise.all(children.map(readDroppedEntry));
    return nested.flat();
  }

  throw new Error(`The browser couldn't read "${entry.name}". Check folder access or choose files instead.`);
}

export function validateUploadPath(path: string, file: File): string | null {
  const segments = path.split(/[\\/]/);
  if (!path.trim() || path.length > MAX_UPLOAD_PATH_LENGTH) return "File path is empty or exceeds 1,024 characters.";
  if (segments.some((segment) => !segment || segment === "." || segment === "..")) return "File path contains an invalid path segment.";
  if (file.name.length > MAX_FILE_NAME_LENGTH) return "File name exceeds 255 characters.";
  if (/[<>:"|?*\u0000-\u001f]/.test(file.name)) return "File name contains characters that are not allowed.";
  if (file.size > MAX_UPLOAD_FILE_SIZE) return "File exceeds the current 100 MB upload limit.";
  return null;
}

