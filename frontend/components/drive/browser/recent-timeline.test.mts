import assert from "node:assert/strict";
import test from "node:test";
import { recentTimelineDays } from "./recent-timeline.ts";

test("recent timeline uses local calendar days and exact window boundaries", () => {
  const today = new Date(2026, 10, 7, 12);
  const timestamp = (day: number, hour = 0) => new Date(2026, 10, day, hour).toISOString();
  const days = recentTimelineDays([
    { modifiedAt: timestamp(-6) },
    { modifiedAt: timestamp(-6, 23) },
    { modifiedAt: timestamp(-7, 23) },
    { modifiedAt: timestamp(6, 23) },
    { modifiedAt: timestamp(7) },
    { modifiedAt: timestamp(8) },
    { modifiedAt: "invalid" },
    {},
  ], today);
  assert.equal(days.length, 14);
  assert.equal(days[0].date.getMonth(), 9);
  assert.equal(days[0].date.getDate(), 25);
  assert.equal(days[0].count, 2);
  assert.equal(days[12].count, 1);
  assert.equal(days[13].count, 1);
  assert.equal(days.reduce((total, day) => total + day.count, 0), 4);
});

test("recent timeline includes zero days and crosses the year chronologically", () => {
  const days = recentTimelineDays([], new Date(2027, 0, 3));
  assert.equal(days[0].date.getFullYear(), 2026);
  assert.equal(days[0].date.getMonth(), 11);
  assert.equal(days[0].date.getDate(), 21);
  assert.equal(days[13].date.getDate(), 3);
  assert.ok(days.every((day) => day.count === 0));
  assert.ok(days.every((day, index) => index === 0 || day.date > days[index - 1].date));
});
