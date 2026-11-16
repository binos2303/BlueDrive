import test from "node:test";
import assert from "node:assert/strict";
import {
  isDownloadSelectionSupported, isExpectedDownloadMimeType,
} from "./drive-download-policy.ts";

test("one folder downloads as ZIP; mixed or multiple folders are rejected", () => {
  assert.equal(isDownloadSelectionSupported([{ type: "folder" }]), true);
  assert.equal(isDownloadSelectionSupported([{ type: "folder" }, { type: "document" }]), false);
  assert.equal(isDownloadSelectionSupported([{ type: "folder" }, { type: "folder" }]), false);
});

test("multiple files remain eligible for sequential download", () => {
  assert.equal(isDownloadSelectionSupported([{ type: "document" }, { type: "image" }]), true);
  assert.equal(isDownloadSelectionSupported([]), false);
});

test("the binary transport rejects HTML/JSON success responses", () => {
  assert.equal(isExpectedDownloadMimeType("application/zip", "application/zip"), true);
  assert.equal(isExpectedDownloadMimeType("Application/ZIP; charset=binary", "application/zip"), true);
  assert.equal(isExpectedDownloadMimeType("application/json", "application/zip"), false);
  assert.equal(isExpectedDownloadMimeType("text/html", "application/zip"), false);
  assert.equal(isExpectedDownloadMimeType(null, "application/zip"), false);
});
