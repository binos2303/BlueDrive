import assert from "node:assert/strict";
import test from "node:test";
import { getDriveDropKind, preferClipboardFileList } from "./drive-upload-utils.ts";

const internalMime = "application/x-bluedrive-item";

test("Kéo mục trong Drive được nhận là Move, kể cả khi trình duyệt có thêm Files", () => {
  assert.equal(getDriveDropKind(["Files", internalMime], internalMime), "internal");
});

test("File từ máy tính được nhận là Upload", () => {
  assert.equal(getDriveDropKind(["Files"], internalMime), "files");
});

test("Dữ liệu kéo không được hỗ trợ không biến thành upload", () => {
  assert.equal(getDriveDropKind(["text/plain"], internalMime), "unsupported");
  assert.equal(getDriveDropKind([], internalMime), "unsupported");
});

test("Không tạo bản sao trùng nếu clipboard.files và clipboard.items cùng chứa file", () => {
  const file = { name: "a.txt" };
  const selected = preferClipboardFileList([file], [file]);
  assert.equal(selected.length, 1);
  assert.equal(selected[0], file);
});

test("Fallback sang clipboard.items khi clipboard.files rỗng", () => {
  const file = { name: "b.txt" };
  assert.deepEqual(preferClipboardFileList([], [file]), [file]);
});

test("Clipboard không có file không khởi tạo hàng đợi", () => {
  assert.deepEqual(preferClipboardFileList([], []), []);
});
