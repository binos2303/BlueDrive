import assert from "node:assert/strict";
import test from "node:test";
import { effectiveSessionPolicy, validateAdminSettingsDraft } from "./admin-settings-policy.ts";

const valid = { display_name: "BlueDrive Cloud", reason: "Approved naming update", revision: 0 };

test("accepts an auditable, changed console name", () => {
  assert.equal(validateAdminSettingsDraft(valid, "BlueDrive"), null);
});

test("rejects no-op and invalid or unprintable names", () => {
  assert.match(validateAdminSettingsDraft({ ...valid, display_name: "BlueDrive" }, "BlueDrive")!, /No change/);
  assert.match(validateAdminSettingsDraft({ ...valid, display_name: "\nBad" }, "BlueDrive")!, /printable/);
  assert.match(validateAdminSettingsDraft({ ...valid, display_name: "x" }, "BlueDrive")!, /2–80/);
});

test("rejects missing audit reason and malformed version", () => {
  assert.match(validateAdminSettingsDraft({ ...valid, reason: "short" }, "BlueDrive")!, /audit reason/);
  assert.match(validateAdminSettingsDraft({ ...valid, revision: -1 }, "BlueDrive")!, /version/);
  assert.match(validateAdminSettingsDraft({ ...valid, revision: 2147483648 }, "BlueDrive")!, /version/);
});

test("session policy text describes actual cookie behavior, not idle timeout", () => {
  assert.equal(effectiveSessionPolicy(1200, true), "20 minutes maximum cookie age; expires at browser close");
  assert.equal(effectiveSessionPolicy(3600, false), "60 minutes maximum cookie age");
  assert.equal(effectiveSessionPolicy(90, false), "90 seconds maximum cookie age");
});
