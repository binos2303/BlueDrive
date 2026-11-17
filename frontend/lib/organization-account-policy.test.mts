import assert from "node:assert/strict";
import test from "node:test";
import { finiteQuotaBytes, organizationInviteFragment } from "./organization-account-policy.ts";

test("finite quotas include zero and preserve the largest whole GiB safe integer", () => {
  assert.equal(finiteQuotaBytes("0"), 0);
  assert.equal(finiteQuotaBytes(" 2 "), 2 * 1024 ** 3);
  const maximum = Math.floor(Number.MAX_SAFE_INTEGER / 1024 ** 3);
  assert.equal(finiteQuotaBytes(String(maximum)), maximum * 1024 ** 3);
  assert.throws(() => finiteQuotaBytes(String(maximum + 1)));
});

test("quota entry rejects negative, fractional, nondecimal and unlimited values", () => {
  for (const value of ["", " ", "-1", "+1", "0.5", "1e3", "0x10", "Infinity", "NaN", "9007199254740991"]) {
    assert.throws(() => finiteQuotaBytes(value), value);
  }
});

test("organization invitation accepts one fragment credential pair only", () => {
  assert.deepEqual(organizationInviteFragment("#uid=fixture-user&token=fixture-invitation"), { uid: "fixture-user", token: "fixture-invitation" });
  for (const fragment of ["", "#uid=fixture-user", "?uid=fixture-user&token=fixture-invitation", "#uid=a&uid=b&token=fixture", "#uid=a&token=a&token=b", "#uid=a%0A&token=b", `#uid=${"x".repeat(129)}&token=b`, `#uid=a&token=${"x".repeat(257)}`]) {
    assert.equal(organizationInviteFragment(fragment), null);
  }
});
