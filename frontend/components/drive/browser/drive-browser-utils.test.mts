import assert from "node:assert/strict";
import test from "node:test";
import { listViewForTitle, parseSize, sortDriveItems } from "./drive-display-utils.ts";
import type { DriveItem } from "./types.ts";
import { validateUploadPath } from "./drive-upload-utils.ts";

test("Drive routes map to their existing API list views", () => {
  assert.equal(listViewForTitle("My Drive"), "drive");
  assert.equal(listViewForTitle("Recent"), "recent");
  assert.equal(listViewForTitle("Workspace files"), "drive");
  assert.equal(listViewForTitle("Trash"), "trash");
  assert.equal(listViewForTitle("Shared with me"), "shared");
  assert.equal(listViewForTitle("Starred"), "starred");
  assert.equal(listViewForTitle("Other"), null);
});

test("file size sorting uses byte values", () => {
  assert.equal(parseSize("1 KB"), 1024);
  assert.equal(parseSize("1.5 MB"), 1572864);
  assert.equal(parseSize("2 GB"), 2 * 1024 ** 3);
  assert.equal(parseSize("unknown"), 0);
});

test("modified sorting uses timestamps across years and within one day", () => {
  const item = (id: number, modified: string, modifiedAt?: string): DriveItem => ({
    id, name: String(id), modified, modifiedAt, owner: "You", ownerInitials: "Y", size: "1 B", type: "document",
  });
  const source = [
    item(3, "Dec 31, 2025", "2025-12-31T18:00:00Z"),
    item(1, "Jan 1, 2024", "2024-01-01T10:00:00Z"),
    item(2, "Dec 31, 2025", "2025-12-31T01:00:00Z"),
    item(4, "Unknown"), item(5, "Unknown", "invalid"),
  ];
  const folder: DriveItem = { ...source[0], id: 6, type: "folder" };
  assert.deepEqual(sortDriveItems([...source, folder], "modified", "asc").map((entry) => entry.id), [6, 1, 2, 3, 4, 5]);
  assert.deepEqual(sortDriveItems([...source, folder], "modified", "desc").map((entry) => entry.id), [6, 3, 2, 1, 4, 5]);
  assert.deepEqual(source.map((entry) => entry.id), [3, 1, 2, 4, 5]);
});

test("upload validation accepts ordinary paths", () => {
  const file = new File(["hello"], "hello.txt", { type: "text/plain" });
  assert.equal(validateUploadPath("folder/hello.txt", file), null);
  assert.equal(validateUploadPath("folder\\hello.txt", file), null);
});

test("upload validation rejects traversal and malformed paths", () => {
  const file = new File(["hello"], "hello.txt");
  assert.match(validateUploadPath("folder/../hello.txt", file) ?? "", /invalid path segment/i);
  assert.match(validateUploadPath("/hello.txt", file) ?? "", /invalid path segment/i);
  assert.match(validateUploadPath("folder//hello.txt", file) ?? "", /invalid path segment/i);
  assert.match(validateUploadPath("", file) ?? "", /empty|exceeds/i);
});

test("upload validation enforces configured size and name bounds", () => {
  const oversizedFile = { name: "hello.txt", size: 100 * 1024 * 1024 + 1 } as File;
  assert.match(validateUploadPath("hello.txt", oversizedFile) ?? "", /100 MB/i);
  const longName = { name: `${"a".repeat(256)}.txt`, size: 0 } as File;
  assert.match(validateUploadPath("some-file.txt", longName) ?? "", /255 characters/);
  const forbiddenName = { name: "bad?.txt", size: 0 } as File;
  assert.match(validateUploadPath("bad?.txt", forbiddenName) ?? "", /not allowed/);
});
