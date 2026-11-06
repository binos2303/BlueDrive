import assert from "node:assert/strict";
import test from "node:test";
import { sortDriveItems, parseSize } from "./drive-display-utils.ts";
import type { DriveItem } from "./types.ts";

function item(id: number, name: string, type: DriveItem["type"], size = "0 B", modified = "2026-01-01"): DriveItem {
  return { id, name, type, size, modified, owner: "", ownerInitials: "" };
}

const names = (items: DriveItem[]) => items.map((entry) => entry.name);

test("folders stay ahead of files for ascending and descending order", () => {
  const source = [
    item(1, "a-file", "document"), item(2, "z-folder", "folder"),
    item(3, "b-folder", "folder"), item(4, "z-file", "document"),
  ];
  assert.deepEqual(names(sortDriveItems(source, "name", "asc")), ["b-folder", "z-folder", "a-file", "z-file"]);
  assert.deepEqual(names(sortDriveItems(source, "name", "desc")), ["z-folder", "b-folder", "z-file", "a-file"]);
});

test("natural name sorting preserves human numeric order", () => {
  const source = [item(1, "File 10", "document"), item(2, "File 2", "document"), item(3, "File 1", "document")];
  assert.deepEqual(names(sortDriveItems(source, "name", "asc")), ["File 1", "File 2", "File 10"]);
});

test("modified sorting uses the previous localeCompare numeric behavior", () => {
  const source = [item(1, "a", "document", "0 B", "rev 10"), item(2, "b", "document", "0 B", "rev 2")];
  assert.deepEqual(names(sortDriveItems(source, "modified", "asc")), ["b", "a"]);
});

test("size sort uses byte values rather than textual order", () => {
  const source = [item(1, "1 KB", "document", "1 KB"), item(2, "950 B", "document", "950 B"), item(3, "1 MB", "document", "1 MB")];
  assert.deepEqual(names(sortDriveItems(source, "size", "asc")), ["950 B", "1 KB", "1 MB"]);
  assert.deepEqual(names(sortDriveItems(source, "size", "desc")), ["1 MB", "1 KB", "950 B"]);
});

test("type sort groups folders first and uses the original type comparison", () => {
  const source = [item(1, "image", "image"), item(2, "folder", "folder"), item(3, "document", "document")];
  assert.deepEqual(names(sortDriveItems(source, "type", "asc")), ["folder", "document", "image"]);
  assert.deepEqual(names(sortDriveItems(source, "type", "desc")), ["folder", "image", "document"]);
});

test("sort never mutates the original Drive items array", () => {
  const source = [item(1, "z", "document"), item(2, "a", "document")];
  const snapshot = source.map(({ id }) => id);
  sortDriveItems(source, "name", "asc");
  assert.deepEqual(source.map(({ id }) => id), snapshot);
});

test("equal entries retain their original stable order", () => {
  const source = [item(1, "same", "document"), item(2, "same", "document")];
  assert.deepEqual(sortDriveItems(source, "name", "asc").map((entry) => entry.id), [1, 2]);
});

test("size parser retains the original unknown-size fallback", () => {
  assert.equal(parseSize("1 KB"), 1024);
  assert.equal(parseSize("unknown"), 0);
});
