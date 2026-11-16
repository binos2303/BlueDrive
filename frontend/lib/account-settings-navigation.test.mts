import assert from "node:assert/strict";
import test from "node:test";
import { settingsTab, settingsTabs } from "./account-settings-navigation.ts";

test("each Settings section can be restored from its URL", () => {
  for (const tab of settingsTabs) {
    const url = new URL(`/account/settings?section=${tab}`, "https://bluedrive.invalid");
    assert.equal(settingsTab(url.searchParams.get("section")), tab);
  }
});

test("missing, repeated and unknown sections safely open General", () => {
  for (const value of [undefined, null, "unknown", "__proto__", ["privacy", "security"], ""]) {
    assert.equal(settingsTab(value), "general");
  }
});
