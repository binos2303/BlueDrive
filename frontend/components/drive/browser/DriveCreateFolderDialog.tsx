"use client";

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
    <>
      {open && (
        <div
          className="fixed inset-0 z-100 flex items-center justify-center bg-black/30 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !creating) {
              onClose();
            }
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-folder-title"
            className="w-full max-w-126.5 rounded-4xl bg-background px-7.5 pb-7 pt-7.5 shadow-xl"
          >
            <h2
              id="create-folder-title"
              className="mb-6 text-[28px] font-normal tracking-tight text-foreground"
            >
              New folder
            </h2>

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
                <p className="mt-2 text-sm text-red-600" role="alert">
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
          </div>
        </div>
      )}


    </>
  );
}
