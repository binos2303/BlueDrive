"use client";

import Dialog from "@/components/ui/Dialog";

type DriveCreateFolderDialogProps = {
  open: boolean;
  creating: boolean;
  name: string;
  error: string;
  onNameChange: (value: string) => void;
  onClose: () => void;
  onCreate: () => void;
};

export default function DriveCreateFolderDialog({
  open, creating, name, error, onNameChange, onClose, onCreate,
}: DriveCreateFolderDialogProps) {
  return (
    <Dialog open={open} title="New folder" onClose={onClose} closeDisabled={creating}>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                onCreate();
              }}
            >
              <input
                autoFocus
                autoComplete="off"
                maxLength={255}
                value={name}
                onFocus={(event) => event.currentTarget.select()}
                onChange={(event) => onNameChange(event.target.value)}
                placeholder="Untitled folder"
                aria-label="Folder name"
                aria-invalid={Boolean(error)}
                disabled={creating}
                className="h-17.5 w-full rounded-[5px] border-2 border-brand bg-transparent px-4.5 text-[20px] text-foreground outline-none focus:ring-0"
              />

              {error && (
                <p className="mt-2 text-sm text-danger" role="alert">
                  {error}
                </p>
              )}

              <div className="mt-7 flex justify-end gap-2">
                <button
                  type="button"
                  disabled={creating}
                  onClick={() => onClose()}
                  className="min-w-20.5 rounded-lg px-4 py-2.5 text-base font-medium text-brand-contrast hover:bg-brand-soft disabled:opacity-50"
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  disabled={creating || !name.trim()}
                  className="min-w-20.5 rounded-lg px-4 py-2.5 text-base font-medium text-brand-contrast hover:bg-brand-soft disabled:opacity-50"
                >
                  {creating ? "Creating..." : "Create"}
                </button>
              </div>
            </form>
    </Dialog>
  );
}
