"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";

type Metrics = { visible: boolean; height: number; top: number };

export default function CustomScrollArea({ children, className = "", contentClassName = "" }: {
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ pointerY: number; scrollTop: number } | null>(null);
  const [metrics, setMetrics] = useState<Metrics>({ visible: false, height: 0, top: 0 });

  const measure = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const visibleHeight = viewport.clientHeight;
    const contentHeight = viewport.scrollHeight;
    const available = Math.max(0, visibleHeight - 8);
    if (contentHeight <= visibleHeight + 1 || !available) {
      setMetrics({ visible: false, height: 0, top: 0 });
      return;
    }
    const height = Math.max(28, available * visibleHeight / contentHeight);
    const travel = Math.max(0, available - height);
    const top = travel * viewport.scrollTop / Math.max(1, contentHeight - visibleHeight);
    setMetrics({ visible: true, height, top });
  }, []);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const resize = new ResizeObserver(measure);
    resize.observe(viewport);
    if (viewport.firstElementChild) resize.observe(viewport.firstElementChild);
    const mutation = new MutationObserver(measure);
    mutation.observe(viewport, { childList: true, subtree: true, characterData: true });
    const frame = requestAnimationFrame(measure);
    return () => { cancelAnimationFrame(frame); resize.disconnect(); mutation.disconnect(); };
  }, [measure]);

  function handlePointerDown(event: PointerEvent<HTMLDivElement>) {
    const viewport = viewportRef.current;
    const track = trackRef.current;
    if (!viewport || !track || !metrics.visible) return;
    event.preventDefault();
    const thumb = (event.target as HTMLElement).closest('[data-scroll-thumb]');
    if (!thumb) {
      const bounds = track.getBoundingClientRect();
      const trackHeight = Math.max(1, bounds.height - 8);
      const travel = Math.max(1, trackHeight - metrics.height);
      const desired = Math.max(0, Math.min(travel, event.clientY - bounds.top - 4 - metrics.height / 2));
      viewport.scrollTop = desired / travel * (viewport.scrollHeight - viewport.clientHeight);
      measure();
    }
    dragRef.current = { pointerY: event.clientY, scrollTop: viewport.scrollTop };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    const viewport = viewportRef.current;
    const track = trackRef.current;
    if (!drag || !viewport || !track) return;
    const travel = Math.max(1, track.clientHeight - 8 - metrics.height);
    const maxScroll = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
    viewport.scrollTop = drag.scrollTop + (event.clientY - drag.pointerY) * maxScroll / travel;
  }

  function handlePointerEnd() { dragRef.current = null; }

  return (
    <div className={`relative min-w-0 overflow-hidden ${className}`}>
      <div ref={viewportRef} tabIndex={0} role="region" aria-label="Scrollable history"
        onScroll={measure} className="custom-scroll-viewport max-h-76 overflow-y-auto overscroll-contain">
        <div className={contentClassName}>{children}</div>
      </div>
      {metrics.visible && (
        <div ref={trackRef} aria-hidden="true" onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove} onPointerUp={handlePointerEnd}
          onPointerCancel={handlePointerEnd} onLostPointerCapture={handlePointerEnd}
          className="absolute inset-y-0 right-0 w-3 touch-none select-none">
          <div data-scroll-thumb="true" className="absolute right-0 w-1.5 rounded-full bg-border-strong hover:bg-brand"
            style={{ height: `${metrics.height}px`, top: `${metrics.top + 4}px` }} />
        </div>
      )}
    </div>
  );
}
