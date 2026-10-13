"use client";

import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

type DialogProps = {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
};

export default function Dialog({
  open,
  title,
  description,
  onClose,
  children,
  className = "",
}: DialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      className={`m-auto max-h-[min(90vh,48rem)] w-[min(100%-2rem,32rem)] overflow-y-auto rounded-2xl border border-border bg-surface p-0 text-foreground shadow-[var(--shadow-popover)] backdrop:bg-foreground/35 ${className}`}
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
          className="rounded-lg p-2 text-muted transition-colors duration-[var(--motion-fast)] hover:bg-background hover:text-foreground"
        >
          <X size={18} />
        </button>
      </div>
      <div className="p-5">{children}</div>
    </dialog>
  );
}
