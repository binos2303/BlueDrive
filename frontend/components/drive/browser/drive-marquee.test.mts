import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = ts.createSourceFile("useDriveSelection.ts", readFileSync(new URL("./useDriveSelection.ts", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true);
let initializer = "";
function find(node: ts.Node) {
  if (ts.isCallExpression(node) && node.expression.getText(source) === "useEffect"
    && node.arguments[0].getText(source).includes('window.addEventListener("pointermove"')) initializer = node.arguments[0].getText(source);
  ts.forEachChild(node, find);
}
find(source);
assert.ok(initializer);
const compiled = ts.transpileModule(`const effect = ${initializer};`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;

function setup() {
  const listeners = new Map<string, (event: Record<string, unknown>) => void>();
  const frames = new Map<number, () => void>();
  let frameId = 0;
  let reads = 0;
  let selected = new Set<number>();
  let active = true;
  const gesture = { current: { x: 0, y: 0, pointerId: 1, additive: false, baseIds: new Set<number>(), dragged: false } as object | null };
  const nodes = Array.from({ length: 500 }, (_, id) => ({
    dataset: { driveItemId: String(id) },
    getBoundingClientRect: () => { reads++; return { left: 0, right: 100, top: id * 24, bottom: (id + 1) * 24 }; },
  }));
  const window = {
    addEventListener: (name: string, handler: (event: Record<string, unknown>) => void) => listeners.set(name, handler),
    removeEventListener: (name: string) => listeners.delete(name),
    requestAnimationFrame: (callback: () => void) => { frames.set(++frameId, callback); return frameId; },
    cancelAnimationFrame: (id: number) => frames.delete(id),
    setTimeout() {},
  };
  const cleanup = new Function("window", "Element", "containerRef", "selectionStartRef", "marqueeSelectedIdsRef", "setSelectionBox", "setSelectedIds", "setSelectionAnchorId", "setMarqueeActive", `${compiled}; return effect();`)(
    window, class Element {}, { current: { querySelectorAll: () => nodes } }, gesture, { current: selected },
    () => {}, (value: Set<number>) => { selected = value; }, () => {}, (value: boolean) => { active = value; },
  ) as () => void;
  return {
    event: (type: string, x = 50, y = 70, pointerId = 1) => listeners.get(type)?.({ type, clientX: x, clientY: y, pointerId, target: {} }),
    flush: () => { const pending = [...frames.values()]; frames.clear(); pending.forEach((callback) => callback()); },
    snapshot: () => ({ reads, selected: [...selected], active, pending: frames.size }), gesture, cleanup,
  };
}

test("100 pointer moves read 500 item bounds once per frame, using the latest coordinates", () => {
  const run = setup();
  for (let i = 0; i < 100; i++) run.event("pointermove", 50, i);
  assert.equal(run.snapshot().reads, 0);
  assert.equal(run.snapshot().pending, 1);
  run.flush();
  assert.equal(run.snapshot().reads, 500);
  assert.deepEqual(run.snapshot().selected, [0, 1, 2, 3, 4]);
  run.cleanup();
});

test("pointer release commits its final position even before an animation frame", () => {
  const run = setup();
  run.event("pointermove", 50, 30);
  run.event("pointerup", 50, 80);
  assert.deepEqual(run.snapshot().selected, [0, 1, 2, 3]);
  assert.equal(run.snapshot().pending, 0);
  assert.equal(run.snapshot().active, false);
  assert.equal(run.gesture.current, null);
  run.cleanup();
});

test("other pointers, cancellation, blur and cleanup cannot leave a queued gesture", () => {
  for (const end of ["pointercancel", "blur", "cleanup"]) {
    const run = setup();
    run.event("pointermove", 50, 40, 2);
    assert.equal(run.snapshot().reads, 0);
    run.event("pointermove");
    if (end === "cleanup") run.cleanup();
    else run.event(end);
    assert.equal(run.snapshot().pending, 0);
    assert.equal(run.gesture.current, null);
    run.flush();
    assert.equal(run.snapshot().reads, 0);
    if (end !== "cleanup") run.cleanup();
  }
});
