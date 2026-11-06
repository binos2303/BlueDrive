"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import type { DriveItem } from "./types";
import { nextSelectedIds } from "./drive-selection-utils";

type SelectionBox = {
  left: number;
  top: number;
  width: number;
  height: number;
};

type UseDriveSelectionParams = {
  items: readonly DriveItem[];
  sortedItems: readonly DriveItem[];
  containerRef: RefObject<HTMLDivElement | null>;
};

/** Keeps Explorer-style selection behavior local to the Drive browser. */
export default function useDriveSelection({ items, sortedItems, containerRef }: UseDriveSelectionParams) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());
  const [selectionAnchorId, setSelectionAnchorId] = useState<number | null>(null);
  const [marqueeActive, setMarqueeActive] = useState(false);
  const [selectionBox, setSelectionBox] = useState<SelectionBox | null>(null);
  const selectionStartRef = useRef<{
    x: number;
    y: number;
    pointerId: number;
    additive: boolean;
    baseIds: Set<number>;
    dragged: boolean;
  } | null>(null);
  const marqueeSelectedIdsRef = useRef<Set<number>>(new Set());

  const selectedItems = useMemo(
    () => items.filter((item) => selectedIds.has(item.id)),
    [items, selectedIds],
  );

  // Some successful actions clear IDs only; preserve their existing anchor behavior.
  const clearSelectedIds = useCallback(() => setSelectedIds(new Set()), []);
  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
    setSelectionAnchorId(null);
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (
        event.target instanceof Element
        && event.target.closest('[role="menu"], dialog[open]')
      ) return;
      clearSelection();
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [clearSelection]);

  function handleItemClick(event: ReactMouseEvent<HTMLElement>, id: number) {
    // A marquee drag can cause a synthetic click on the last item.
    const clickedNode = event.currentTarget;
    if (clickedNode.dataset.suppressSelectionClick === "true") {
      delete clickedNode.dataset.suppressSelectionClick;
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    if (event.shiftKey) {
      event.preventDefault();
      if (selectionAnchorId === null) setSelectionAnchorId(id);
    } else {
      setSelectionAnchorId(id);
    }
    const modifiers = {
      shiftKey: event.shiftKey,
      ctrlKey: event.ctrlKey,
      metaKey: event.metaKey,
    };
    const orderedIds = sortedItems.map((item) => item.id);
    setSelectedIds((current) => nextSelectedIds(current, orderedIds, id, selectionAnchorId, modifiers));
  }

  function toggleItem(id: number) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setSelectionAnchorId(id);
  }

  function handleMarqueePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || event.shiftKey) return;
    const target = event.target;
    if (!(target instanceof Element)) return;
    // Starting on a row/card body is allowed: a simple click still selects that item,
    // while moving beyond the drag threshold turns the gesture into a marquee.
    // Keep menus, action buttons, sort controls, and explicit drag handles independent.
    if (target.closest(
      'thead, button, a, input, select, textarea, [role="menu"], [role="toolbar"], dialog[open], [contenteditable="true"], [data-no-marquee-selection="true"]',
    )) return;

    const additive = event.ctrlKey || event.metaKey;
    const baseIds = new Set(selectedIds);
    selectionStartRef.current = {
      x: event.clientX,
      y: event.clientY,
      pointerId: event.pointerId,
      additive,
      baseIds,
      dragged: false,
    };
    marqueeSelectedIdsRef.current = new Set(additive ? baseIds : []);
    setSelectionBox(null);
    setMarqueeActive(true);
  }

  useEffect(() => {
    function handlePointerMove(event: PointerEvent) {
      const start = selectionStartRef.current;
      const container = containerRef.current;
      if (!start || !container || event.pointerId !== start.pointerId) return;

      const dx = event.clientX - start.x;
      const dy = event.clientY - start.y;
      if (!start.dragged && Math.hypot(dx, dy) < 4) return;
      start.dragged = true;

      const left = Math.min(start.x, event.clientX);
      const top = Math.min(start.y, event.clientY);
      const right = Math.max(start.x, event.clientX);
      const bottom = Math.max(start.y, event.clientY);
      setSelectionBox({ left, top, width: right - left, height: bottom - top });

      const next = new Set(start.additive ? start.baseIds : []);
      const itemNodes = container.querySelectorAll<HTMLElement>("[data-drive-item-id]");
      itemNodes.forEach((node) => {
        const rect = node.getBoundingClientRect();
        const intersects = rect.left <= right
          && rect.right >= left
          && rect.top <= bottom
          && rect.bottom >= top;
        if (intersects) {
          const id = Number(node.dataset.driveItemId);
          if (Number.isSafeInteger(id)) next.add(id);
        }
      });
      marqueeSelectedIdsRef.current = next;
      setSelectedIds(next);
    }

    function finishPointer(event: PointerEvent) {
      const start = selectionStartRef.current;
      if (!start || (event.pointerId !== undefined && event.pointerId !== start.pointerId)) return;
      if (start.dragged) {
        // Mark the item under the pointer so its synthetic post-drag click is ignored.
        // The marker is stored on the DOM item rather than a ref read by the render callback.
        const pointerTarget = event.target instanceof Element
          ? event.target.closest<HTMLElement>("[data-drive-item-id]")
          : null;
        if (pointerTarget) {
          pointerTarget.dataset.suppressSelectionClick = "true";
          window.setTimeout(() => {
            if (pointerTarget.dataset.suppressSelectionClick === "true") {
              delete pointerTarget.dataset.suppressSelectionClick;
            }
          }, 0);
        }
        const container = containerRef.current;
        const selectedInListOrder = container
          ? Array.from(container.querySelectorAll<HTMLElement>("[data-drive-item-id]"))
            .map((node) => Number(node.dataset.driveItemId))
            .filter((id) => Number.isSafeInteger(id) && marqueeSelectedIdsRef.current.has(id))
          : [];
        if (selectedInListOrder.length) {
          setSelectionAnchorId(selectedInListOrder[selectedInListOrder.length - 1]);
        }
      } else if (!start.additive) {
        // Clicking blank space clears selection; a row/card click handler will then
        // select the clicked item if the pointer was released on one.
        const target = event.target;
        const clickedItem = target instanceof Element && target.closest('[data-drive-item-id]');
        if (!clickedItem) {
          setSelectedIds(new Set());
          setSelectionAnchorId(null);
        }
      }
      selectionStartRef.current = null;
      setSelectionBox(null);
      setMarqueeActive(false);
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", finishPointer);
    window.addEventListener("pointercancel", finishPointer);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", finishPointer);
      window.removeEventListener("pointercancel", finishPointer);
    };
  }, [containerRef]);

  return {
    selectedIds,
    selectedItems,
    marqueeActive,
    selectionBox,
    clearSelection,
    clearSelectedIds,
    handleItemClick,
    toggleItem,
    handleMarqueePointerDown,
  };
}
