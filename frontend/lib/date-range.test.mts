import assert from "node:assert/strict";
import test from "node:test";
import { inLocalDateRange } from "./date-range.ts";

test("From and To are inclusive, independently optional local-day boundaries", () => {
  const value = new Date(2026, 10, 7, 12).toISOString();
  assert.equal(inLocalDateRange(value, "2026-11-01", ""), true);
  assert.equal(inLocalDateRange(value, "2026-11-08", ""), false);
  assert.equal(inLocalDateRange(value, "", "2026-11-07"), true);
  assert.equal(inLocalDateRange(value, "", "2026-11-06"), false);
  assert.equal(inLocalDateRange(value, "2026-11-07", "2026-11-07"), true);
  assert.equal(inLocalDateRange(value, "", ""), true);
  assert.equal(inLocalDateRange(value, "2026-11-08", "2026-11-01"), false);
  assert.equal(inLocalDateRange("invalid", "", ""), false);
});

test("the whole local day is included, including midnight boundaries", () => {
  for (const hour of [0, 12, 23]) {
    assert.equal(inLocalDateRange(new Date(2026, 10, 7, hour, 59).toISOString(), "2026-11-07", "2026-11-07"), true);
  }
  assert.equal(inLocalDateRange(new Date(2026, 10, 8, 0).toISOString(), "", "2026-11-07"), false);
});
