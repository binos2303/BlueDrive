"use client";

import type { FormEvent } from "react";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";

type DriveShareDialogProps = {
  open: boolean;
  targetCount: number;
  sharing: boolean;
  error: string | null;
  email: string;
  permission: "viewer" | "editor";
  onClose: () => void;
  onEmailChange: (value: string) => void;
  onPermissionChange: (value: "viewer" | "editor") => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export default function DriveShareDialog({
  open, targetCount, sharing, error, email, permission, onClose,
  onEmailChange, onPermissionChange, onSubmit,
}: DriveShareDialogProps) {
  return (
    <Dialog open={open} title={`Share ${targetCount} item${targetCount === 1 ? "" : "s"}`}
      description="Grant access to an existing BlueDrive account by email."
      onClose={onClose} closeDisabled={sharing}>
          <form onSubmit={onSubmit}>
            <div className="space-y-4 px-5 py-5">
              {error && <p role="alert" className="text-sm text-danger">{error}</p>}
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
              <p className="text-xs leading-5 text-muted">The recipient must already have an active BlueDrive account registered with this email. BlueDrive will attempt to send a notification if outgoing email is configured; access permissions are applied independently.</p>
            </div>
            <footer className="flex justify-end gap-2 border-t border-border bg-background px-5 py-4">
              <Button variant="ghost" onClick={() => onClose()} disabled={sharing}>Cancel</Button>
              <Button type="submit" disabled={sharing || !email.trim()}>{sharing ? "Sharing…" : "Share"}</Button>
            </footer>
          </form>
    </Dialog>
  );
}
