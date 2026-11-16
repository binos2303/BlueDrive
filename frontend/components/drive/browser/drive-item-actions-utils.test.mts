import assert from "node:assert/strict";
import test from "node:test";
import { applyStarredToItems, destructiveActionConfig, executeDuplicateItems, renameTargetForSelection } from "./drive-item-actions-utils.ts";
import type { DriveItem } from "./types.ts";

const item = (id: number, name: string, type: DriveItem["type"], folderId?: number, canManage?: boolean): DriveItem =>
  ({ id, name, type, folderId, canManage, modified: "", owner: "", ownerInitials: "", size: "" });

test("Rename maps ordinary file ID and name without changing type", () => {
  assert.deepEqual(renameTargetForSelection([item(12, "report.pdf", "document")], "My Drive"),
    { kind: "file", id: 12, name: "report.pdf" });
});

test("Rename uses folderId and handles negative surrogate ID fallback", () => {
  assert.deepEqual(renameTargetForSelection([item(-9, "Folder", "folder", 71)], "My Drive"),
    { kind: "folder", id: 71, name: "Folder" });
  assert.deepEqual(renameTargetForSelection([item(-9, "Folder", "folder")], "My Drive"),
    { kind: "folder", id: 9, name: "Folder" });
});

test("Rename rejects multi-selection, no selection, Trash and explicitly read-only items", () => {
  assert.equal(renameTargetForSelection([], "My Drive"), null);
  assert.equal(renameTargetForSelection([item(1, "One", "document"), item(2, "Two", "document")], "My Drive"), null);
  assert.equal(renameTargetForSelection([item(1, "One", "document")], "Trash"), null);
  assert.equal(renameTargetForSelection([item(1, "One", "document", undefined, false)], "My Drive"), null);
});

test("Rename accepts canManage omitted exactly as before", () => {
  assert.equal(renameTargetForSelection([item(1, "One", "image")], "Recent")?.kind, "file");
});

test("Duplicate success preserves POST → clear → tree → refresh → toast ordering", async () => {
  const events: string[] = [];
  const targets = [item(1, "One", "document")];
  await executeDuplicateItems(targets, {
    postItemAction: async (received) => { assert.equal(received, targets); events.push("post"); return { detail: "Created 1 copy." }; },
    clearSelectedIds: () => events.push("clear"),
    notifyFolderTreeChanged: () => events.push("tree"),
    refreshItems: async () => { events.push("refresh"); },
    setToast: (text) => events.push(`toast:${text}`),
  });
  assert.deepEqual(events, ["post", "clear", "tree", "refresh", "toast:Created 1 copy."]);
});

test("Duplicate uses original success fallback when server detail is empty", async () => {
  const messages: string[] = [];
  await executeDuplicateItems([item(1, "One", "document")], {
    postItemAction: async () => ({ detail: "" }),
    clearSelectedIds: () => {}, notifyFolderTreeChanged: () => {}, refreshItems: async () => {},
    setToast: (message) => messages.push(message),
  });
  assert.deepEqual(messages, ["Duplicate created successfully."]);
});

test("Duplicate API error retains selection and does not reload", async () => {
  const events: string[] = [];
  await executeDuplicateItems([item(1, "One", "document")], {
    postItemAction: async () => { throw new Error("Access denied"); },
    clearSelectedIds: () => events.push("clear"), notifyFolderTreeChanged: () => events.push("tree"),
    refreshItems: async () => { events.push("refresh"); }, setToast: (message) => events.push(message),
  });
  assert.deepEqual(events, ["Access denied"]);
});

test("Duplicate refresh failure keeps existing error reporting after clearing selection", async () => {
  const events: string[] = [];
  await executeDuplicateItems([item(1, "One", "document")], {
    postItemAction: async () => { events.push("post"); return { detail: "Done" }; },
    clearSelectedIds: () => events.push("clear"), notifyFolderTreeChanged: () => events.push("tree"),
    refreshItems: async () => { throw new Error("Could not reload"); }, setToast: (message) => events.push(message),
  });
  assert.deepEqual(events, ["post", "clear", "tree", "Could not reload"]);
});


test("Đánh dấu sao đúng mục theo cả ID và loại", () => {
  const file = item(7, "File", "document");
  const folder = item(7, "Folder", "folder", 7);
  const unchanged = item(8, "Another", "document");
  const source = [file, folder, unchanged];
  const result = applyStarredToItems(source, [folder], true);
  assert.equal(result[0].starred, undefined);
  assert.equal(result[1].starred, true);
  assert.equal(result[2], unchanged);
  assert.equal(source[1].starred, undefined);
});

test("Bỏ đánh dấu sao không sửa dữ liệu nguồn", () => {
  const starred = { ...item(21, "Report", "document"), starred: true };
  const source = [starred];
  const result = applyStarredToItems(source, [starred], false);
  assert.equal(result[0].starred, false);
  assert.equal(source[0].starred, true);
});


test("Chuyển vào thùng rác dùng đúng API", () => {
  assert.deepEqual(destructiveActionConfig("trash"), {
    path: "/drive/api/items/trash/", defaultMessage: "Moved to Trash.",
  });
});

test("Xóa vĩnh viễn dùng endpoint riêng", () => {
  assert.deepEqual(destructiveActionConfig("delete"), {
    path: "/drive/api/items/delete/", defaultMessage: "Permanently deleted.",
  });
});
