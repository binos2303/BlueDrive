import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const light = css.match(/:root\s*\{([^}]+)\}/)![1];
const dark = css.match(/html\[data-theme="dark"\]\s*\{([^}]+)\}/)![1];
const tokens = (block: string) => Object.fromEntries([...block.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})\s*;/gi)].map((m) => [m[1], m[2]]));
function luminance(hex: string) {
  const channels = hex.slice(1).match(/../g)!.map((part) => parseInt(part, 16) / 255)
    .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}

for (const [name, palette] of [["light", tokens(light)], ["dark", { ...tokens(light), ...tokens(dark) }]] as const) {
  test(`${name} semantic text/background pairs meet normal-text AA contrast`, () => {
    for (const [foreground, background] of [
      ["foreground", "surface"], ["muted", "surface"], ["muted", "background"],
      ["success", "success-soft"], ["warning", "warning-soft"], ["danger", "danger-soft"],
      ["brand-primary-contrast", "brand-primary-soft"], ["on-accent", "brand-primary-contrast"],
      ["brand-primary-contrast", "surface"], ["brand-primary-contrast", "background"],
      ["on-accent", "brand-primary-hover"],
    ]) {
      const a = luminance(palette[foreground]);
      const b = luminance(palette[background]);
      const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      assert.ok(ratio >= 4.5, `${foreground}/${background}: ${ratio.toFixed(2)}:1`);
    }
  });
}
