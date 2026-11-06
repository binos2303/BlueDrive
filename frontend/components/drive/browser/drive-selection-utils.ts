/** Pure selection transition used by the Drive browser. No API or DOM dependencies. */
export type SelectionModifiers = Readonly<{
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
}>;

export function nextSelectedIds(
  current: ReadonlySet<number>,
  orderedIds: readonly number[],
  id: number,
  anchorId: number | null,
  modifiers: SelectionModifiers,
): Set<number> {
  if (modifiers.shiftKey) {
    const anchor = anchorId ?? id;
    let anchorIndex = orderedIds.indexOf(anchor);
    const targetIndex = orderedIds.indexOf(id);
    if (anchorIndex < 0) anchorIndex = targetIndex;
    if (targetIndex < 0) return new Set(current);

    const start = Math.min(anchorIndex, targetIndex);
    const end = Math.max(anchorIndex, targetIndex);
    const selected = modifiers.ctrlKey || modifiers.metaKey
      ? new Set(current)
      : new Set<number>();
    orderedIds.slice(start, end + 1).forEach((value) => selected.add(value));
    return selected;
  }
  if (modifiers.ctrlKey || modifiers.metaKey) {
    const selected = new Set(current);
    if (selected.has(id)) selected.delete(id);
    else selected.add(id);
    return selected;
  }
  return new Set([id]);
}
