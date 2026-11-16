import test from "node:test";
import assert from "node:assert/strict";
import {
  isPreviewSizeAllowed, isPreviewSupported, normalizePreviewMimeType, MAX_PREVIEW_BYTES,
} from "./file-preview-policy.ts";

test("only backend-supported MIME types can render inline", () => {
  for (const mime of ["image/png", "image/jpeg", "image/gif", "image/webp", "text/plain"]) {
    assert.equal(isPreviewSupported(mime), true, mime);
  }
  for (const mime of ["application/pdf", "text/html", "image/svg+xml", "application/octet-stream"]) {
    assert.equal(isPreviewSupported(mime), false, mime);
  }
});

test("MIME normalization strips charset and handles case", () => {
  assert.equal(normalizePreviewMimeType(" TEXT/PLAIN ;charset=utf-8"), "text/plain");
  assert.equal(isPreviewSupported("TEXT/PLAIN; charset=utf-8"), true);
});

test("preview prevents large or invalid sizes", () => {
  assert.equal(isPreviewSizeAllowed(0), true);
  assert.equal(isPreviewSizeAllowed(MAX_PREVIEW_BYTES), true);
  for (const bytes of [-1, MAX_PREVIEW_BYTES + 1, Infinity, NaN, 0.5]) {
    assert.equal(isPreviewSizeAllowed(bytes), false);
  }
});
