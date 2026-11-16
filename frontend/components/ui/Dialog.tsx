"use client";

import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

type DialogProps = {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  closeDisabled?: boolean;
  children: ReactNode;
  className?: string;
};

export default function Dialog({
  open,
  title,
  description,
  onClose,
  closeDisabled = false,
  children,
  className = "",
}: DialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
    return () => {
      // Đóng trước khi trả focus; native dialog bị unmount có thể mất điểm mở lại.
      if (dialog.open) dialog.close();
      if (open && returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
    };
  }, [open]);

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      onCancel={(event) => {
        event.preventDefault();
        if (!closeDisabled) onClose();
      }}
      className={`m-auto max-h-[min(90dvh,48rem)] w-[min(calc(100%_-_2rem),32rem)] overflow-y-auto rounded-2xl border border-border bg-surface p-0 text-foreground shadow-[var(--shadow-popover)] backdrop:bg-foreground/35 ${className}`}
    >
      <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
        <div>
          <h2 id={titleId} className="text-base font-semibold">{title}</h2>
          {description && <p id={descriptionId} className="mt-1 text-sm text-muted">{description}</p>}
        </div>
        <button
          type="button"
          aria-label="Close dialog"
          onClick={onClose}
          disabled={closeDisabled}
          className="ui-control rounded-lg p-2 text-muted transition-colors duration-[var(--motion-fast)] hover:bg-background hover:text-foreground"
        >
          <X size={18} />
        </button>
      </div>
      <div className="p-5">{children}</div>
    </dialog>
  );
}
