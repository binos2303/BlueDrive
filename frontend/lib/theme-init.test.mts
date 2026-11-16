import assert from "node:assert/strict";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { THEME_INIT_SCRIPT } from "./theme.ts";

test("pre-paint theme respects saved preferences and safely falls back to the system", () => {
  for (const [saved, systemDark, expected] of [
    ["dark", false, "dark"], ["light", true, "light"], ["system", true, "dark"],
    [null, false, "light"], ["invalid", true, "dark"], ["blocked", true, "dark"],
    ['dark";throw new Error("injected")', false, "light"],
  ] as const) {
    const root = { dataset: {} as { theme?: string }, style: {} as { colorScheme?: string } };
    runInNewContext(THEME_INIT_SCRIPT, {
      window: {
        localStorage: { getItem(key: string) { assert.equal(key, "securedrive:theme-preference:v1"); if (saved === "blocked") throw new Error("Storage blocked"); return saved; } },
        matchMedia: () => ({ matches: systemDark }),
      },
      document: { documentElement: root },
    });
    assert.equal(root.dataset.theme, expected);
    assert.equal(root.style.colorScheme, expected);
  }
});
