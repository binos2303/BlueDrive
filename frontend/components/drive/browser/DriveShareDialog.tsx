"use client";

import type { FormEvent } from "react";
import Button from "@/components/ui/Button";

type DriveShareDialogProps = {
  open: boolean;
  targetCount: number;
  sharing: boolean;
  email: string;
  permission: "viewer" | "editor";
  onClose: () => void;
  onEmailChange: (value: string) => void;
  onPermissionChange: (value: "viewer" | "editor") => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export default function DriveShareDialog({
  open, targetCount, sharing, email, permission, onClose,
  onEmailChange, onPermissionChange, onSubmit,
}: DriveShareDialogProps) {
  return (
    <>
      {open && (
        <div className="fixed inset-0 z-100 flex items-center justify-center bg-black/40 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !sharing) onClose(); }}>
          <form onSubmit={(event) => onSubmit(event)} aria-labelledby="share-items-title" className="w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-surface shadow-xl">
            <header className="border-b border-border px-5 py-4">
              <h2 id="share-items-title" className="text-lg font-semibold text-foreground">Share {targetCount} item{targetCount === 1 ? "" : "s"}</h2>
              <p className="mt-1 text-sm text-muted">Grant access to an existing SecureDrive account by email.</p>
            </header>
            <div className="space-y-4 px-5 py-5">
              <label className="block text-sm font-medium text-foreground">
                Email address
                <input
                  type="email"
                  required
                  autoFocus
                  value={email}
                  onChange={(event) => onEmailChange(event.target.value)}
                  placeholder="name@example.com"
                  autoComplete="email"
                  className="mt-1.5 h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none focus:border-brand-contrast focus:ring-2 focus:ring-brand-soft"
                />
              </label>
              <label className="block text-sm font-medium text-foreground">
                Access level
                <select value={permission} onChange={(event) => onPermissionChange(event.target.value as "viewer" | "editor")} className="mt-1.5 h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none focus:border-brand-contrast focus:ring-2 focus:ring-brand-soft">
                  <option value="viewer">Viewer — can view and download</option>
                  <option value="editor">Editor — can modify shared items</option>
                </select>
              </label>
              <p className="text-xs leading-5 text-muted">The recipient must already have an active SecureDrive account registered with this email. SecureDrive will attempt to send a notification if outgoing email is configured; access permissions are applied independently.</p>
            </div>
            <footer className="flex justify-end gap-2 border-t border-border bg-background px-5 py-4">
              <Button variant="ghost" onClick={() => onClose()} disabled={sharing}>Cancel</Button>
              <Button type="submit" disabled={sharing || !email.trim()}>{sharing ? "Sharing…" : "Share"}</Button>
            </footer>
          </form>
        </div>
      )}


    </>
  );
}
