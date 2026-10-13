"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type ContextMenuAction = {
  label: string;
  onSelect: () => void;
  destructive?: boolean;
  disabled?: boolean;
};

type ContextMenuProps = {
  label: string;
  trigger: ReactNode;
  actions: ContextMenuAction[];
  triggerClassName?: string;
};

type MenuPosition = {
  top: number;
  left: number;
};

export default function ContextMenu({
  label,
  trigger,
  actions,
  triggerClassName,
}: ContextMenuProps) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<MenuPosition>({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLUListElement>(null);
  const menuId = useId();

  useLayoutEffect(() => {
    if (!open || !triggerRef.current || !menuRef.current) return;
    const triggerRect = triggerRef.current.getBoundingClientRect();
    const menuRect = menuRef.current.getBoundingClientRect();
    const margin = 8;
    const left = Math.max(
      margin,
      Math.min(triggerRect.right - menuRect.width, window.innerWidth - menuRect.width - margin),
    );
    const top = Math.max(
      margin,
      Math.min(triggerRect.bottom + 4, window.innerHeight - menuRect.height - margin),
    );
    setPosition({ top, left });
    menuRef.current.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;

    function onPointerDown(event: PointerEvent) {
      if (
        !menuRef.current?.contains(event.target as Node)
        && !triggerRef.current?.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    }

    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function close(restoreFocus = true) {
    setOpen(false);
    if (restoreFocus) requestAnimationFrame(() => triggerRef.current?.focus());
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLUListElement>) {
    const menuItems = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)'),
    );
    const currentIndex = menuItems.indexOf(document.activeElement as HTMLButtonElement);
    if (!menuItems.length) return;

    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      menuItems[(currentIndex + 1) % menuItems.length].focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      menuItems[(currentIndex - 1 + menuItems.length) % menuItems.length].focus();
    } else if (event.key === "Home") {
      event.preventDefault();
      menuItems[0].focus();
    } else if (event.key === "End") {
      event.preventDefault();
      menuItems[menuItems.length - 1].focus();
    } else if (event.key === "Tab") {
      close(false);
      triggerRef.current?.focus();
    }
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
          }
        }}
        className={triggerClassName ?? "inline-flex h-10 w-10 items-center justify-center rounded-[var(--radius-control)] text-muted transition-colors duration-[var(--motion-fast)] hover:bg-background hover:text-foreground"}
      >
        {trigger}
      </button>
      {open && typeof document !== "undefined" && createPortal(
        <ul
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label={label}
          onKeyDown={handleKeyDown}
          style={{ top: position.top, left: position.left }}
          className="fixed z-[70] max-h-[min(70vh,24rem)] min-w-48 overflow-y-auto rounded-xl border border-border bg-surface p-1 shadow-[var(--shadow-popover)]"
        >
          {actions.map((action) => (
            <li key={action.label} role="none">
              <button
                type="button"
                role="menuitem"
                disabled={action.disabled}
                onClick={() => {
                  action.onSelect();
                  close();
                }}
                className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors duration-[var(--motion-fast)] disabled:cursor-not-allowed disabled:opacity-50 ${
                  action.destructive
                    ? "text-danger hover:bg-rose-50"
                    : "text-foreground hover:bg-background"
                }`}
              >
                {action.label}
              </button>
            </li>
          ))}
        </ul>,
        document.body,
      )}
    </>
  );
}
