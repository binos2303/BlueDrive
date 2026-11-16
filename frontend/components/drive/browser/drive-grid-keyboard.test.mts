import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { isValidElement, Children } from "react";
import ts from "typescript";

const require = createRequire(import.meta.url);
const compiled = ts.transpileModule(readFileSync(new URL("./DriveGrid.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const componentModule = { exports: {} as { default: (props: Record<string, unknown>) => unknown } };
new Function("require", "module", "exports", compiled)((name: string) => {
  if (name === "@/components/ui/ContextMenu") return { default: () => null };
  if (name === "./DriveItemIcon") return { renderItemIcon: () => null };
  return require(name);
}, componentModule, componentModule.exports);

type CardProps = {
  "aria-pressed": boolean;
  onKeyDown: (event: { key: string; currentTarget: object; target: object; preventDefault?: () => void }) => void;
};

function articles(tree: unknown): CardProps[] {
  if (!isValidElement<{ children?: React.ReactNode }>(tree)) return [];
  const own = tree.type === "article" ? [tree.props as unknown as CardProps] : [];
  return [...own, ...Children.toArray(tree.props.children).flatMap(articles)];
}

test("folder and file child buttons never activate the containing card", () => {
  let opened = 0;
  let toggled = 0;
  const item = { id: 1, name: "report", type: "folder", folderId: 1 };
  const cards = articles(componentModule.exports.default({
    folderItems: [item], fileItems: [{ ...item, type: "pdf" }], selectedIds: new Set([1]),
    title: "My Drive", createActions: () => [], onOpen: () => opened++, onToggleItem: () => toggled++,
  }));
  assert.equal(cards.length, 2);
  for (const card of cards) {
    assert.equal(card["aria-pressed"], true);
    const currentTarget = {};
    for (const key of ["Enter", " "]) {
      card.onKeyDown({ key, currentTarget, target: {}, preventDefault: () => assert.fail("Child default must be preserved") });
    }
    assert.equal(opened, 0);
    assert.equal(toggled, 0);
  }
  for (const card of cards) {
    const target = {};
    card.onKeyDown({ key: "Enter", currentTarget: target, target });
    card.onKeyDown({ key: " ", currentTarget: target, target, preventDefault() {} });
  }
  assert.equal(opened, 2);
  assert.equal(toggled, 2);
});
