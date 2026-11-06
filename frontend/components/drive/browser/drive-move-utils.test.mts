import assert from "node:assert/strict";
import test from "node:test";
import {
  ITEM_DRAG_TYPE,
  getBreadcrumbMoveDestination,
  serializeDraggedDriveItems,
  resolveDraggedDriveItems,
  executeMoveAndRefresh,
} from "./drive-move-utils.ts";
import type { DriveItem } from "./types.ts";

const item = (id: number, name: string, type: DriveItem["type"], folderId?: number): DriveItem => ({
  id, name, type, folderId, owner: "", ownerInitials: "", modified: "", size: "",
});

const folder = item(-3, "Folder", "folder", 3);
const file = item(41, "Report", "document");

test("MIME nội bộ khác dữ liệu Files từ hệ điều hành", () => {
  assert.equal(ITEM_DRAG_TYPE, "application/x-securedrive-item");
  assert.notEqual(ITEM_DRAG_TYPE, "Files");
});

test("Chỉ My Drive đang ở view drive được nhận drop tại breadcrumb", () => {
  const base = { title: "My Drive", listView: "drive", index: 0, ancestorIds: [10, 20], currentFolderId: 30 };
  assert.equal(getBreadcrumbMoveDestination(base), null);
  assert.equal(getBreadcrumbMoveDestination({ ...base, title: "Trash" }), undefined);
  assert.equal(getBreadcrumbMoveDestination({ ...base, listView: "recent" }), undefined);
});

test("Breadcrumb trả đúng root, các thư mục cha và thư mục hiện tại", () => {
  const base = { title: "My Drive", listView: "drive", index: 0, ancestorIds: [10, 20], currentFolderId: 30 };
  assert.equal(getBreadcrumbMoveDestination({ ...base, index: 0 }), null);
  assert.equal(getBreadcrumbMoveDestination({ ...base, index: 1 }), 10);
  assert.equal(getBreadcrumbMoveDestination({ ...base, index: 2 }), 20);
  assert.equal(getBreadcrumbMoveDestination({ ...base, index: 3 }), 30);
  assert.equal(getBreadcrumbMoveDestination({ ...base, index: 4 }), undefined);
  assert.equal(getBreadcrumbMoveDestination({ ...base, currentFolderId: null, index: 3 }), undefined);
});

test("Payload kéo giữ ID, loại và folderId; mục không tồn tại bị bỏ qua", () => {
  const raw = serializeDraggedDriveItems([folder, file]);
  assert.deepEqual(JSON.parse(raw), { items: [
    { id: -3, type: "folder", folderId: 3 },
    { id: 41, type: "document", folderId: null },
  ] });
  assert.deepEqual(resolveDraggedDriveItems(raw, [file, folder]), [folder, file]);
  assert.deepEqual(resolveDraggedDriveItems('{"items":[{"id":999}]}', [file]), []);
});

test("Phân giải mục từ danh sách hiện hành, không tin thuộc tính trong payload", () => {
  const raw = '{"items":[{"id":41,"type":"folder","folderId":555,"canManage":true}]}';
  assert.deepEqual(resolveDraggedDriveItems(raw, [file]), [file]);
});

test("Payload không hợp lệ gây lỗi để handler hiển thị thông báo phù hợp", () => {
  assert.throws(() => resolveDraggedDriveItems('not-json', [file]), SyntaxError);
});

test("Move dialog giữ thứ tự POST → đóng dialog → bỏ chọn → cập nhật cây → refresh", async () => {
  const events: string[] = [];
  await executeMoveAndRefresh([file], 30, {
    postItemAction: async (path, targets, extra) => {
      assert.equal(path, "/drive/api/items/move/");
      assert.deepEqual(targets, [file]);
      assert.deepEqual(extra, { destination_folder_id: 30 });
      events.push("post");
      return { detail: "Moved" };
    },
    onMoved: () => events.push("close"),
    clearSelectedIds: () => events.push("clear"),
    notifyFolderTreeChanged: () => events.push("tree"),
    refreshItems: async () => { events.push("refresh"); },
  });
  assert.deepEqual(events, ["post", "close", "clear", "tree", "refresh"]);
});

test("Thả vào root gửi destination_folder_id null và không đóng dialog", async () => {
  const events: string[] = [];
  await executeMoveAndRefresh([folder], null, {
    postItemAction: async (_, __, extra) => {
      assert.deepEqual(extra, { destination_folder_id: null });
      events.push("post");
      return { detail: "" };
    },
    clearSelectedIds: () => events.push("clear"),
    notifyFolderTreeChanged: () => events.push("tree"),
    refreshItems: async () => { events.push("refresh"); },
  });
  assert.deepEqual(events, ["post", "clear", "tree", "refresh"]);
});

test("Move API lỗi không báo thành công, giữ nguyên lựa chọn và không refresh", async () => {
  const events: string[] = [];
  await assert.rejects(executeMoveAndRefresh([file], 5, {
    postItemAction: async () => { events.push("post"); throw new Error("Forbidden"); },
    clearSelectedIds: () => events.push("clear"),
    notifyFolderTreeChanged: () => events.push("tree"),
    refreshItems: async () => { events.push("refresh"); },
  }), /Forbidden/);
  assert.deepEqual(events, ["post"]);
});

test("Lỗi refresh sau POST không báo lại thành công; vẫn giữ trình tự cũ", async () => {
  const events: string[] = [];
  await assert.rejects(executeMoveAndRefresh([file], 5, {
    postItemAction: async () => { events.push("post"); return { detail: "Moved" }; },
    clearSelectedIds: () => events.push("clear"),
    notifyFolderTreeChanged: () => events.push("tree"),
    refreshItems: async () => { events.push("refresh"); throw new Error("Refresh failed"); },
  }), /Refresh failed/);
  assert.deepEqual(events, ["post", "clear", "tree", "refresh"]);
});
