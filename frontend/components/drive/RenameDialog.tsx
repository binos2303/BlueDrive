"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";
import Input from "@/components/ui/Input";
import { renameDriveItem, type RenameTarget, type RenameResult } from "@/lib/drive-service";

function RenameDialogContent({
  target, onClose, onRenamed,
}: {
  target: RenameTarget;
  onClose: () => void;
  onRenamed: (result: RenameResult) => void;
}) {
  const [name, setName] = useState(target.name);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const input = inputRef.current;
      if (!input) return;
      const lastDot = target.kind === "file" ? target.name.lastIndexOf(".") : -1;
      input.focus();
      input.setSelectionRange(0, lastDot > 0 ? lastDot : target.name.length);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [target]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const cleaned = name.trim();
    if (!cleaned || cleaned.length > 255) {
      setError("Name must be between 1 and 255 characters.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      onRenamed(await renameDriveItem({ ...target, name: cleaned }));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not rename the item.");
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open title={`Rename ${target.kind}`} onClose={() => { if (!pending) onClose(); }}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        <label className="block space-y-2 text-sm font-medium text-foreground">
          Name
          <Input ref={inputRef} value={name} onChange={(event) => { setName(event.target.value); setError(null); }}
            aria-label="New name" maxLength={255} autoComplete="off" invalid={Boolean(error)} disabled={pending} />
        </label>
        {target.kind === "file" && <p className="text-xs text-muted">Keep the original file extension.</p>}
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" disabled={pending} onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={pending || !name.trim()} loading={pending}>Save</Button>
        </div>
      </form>
    </Dialog>
  );
}

export default function RenameDialog(props: {
  target: RenameTarget | null;
  onClose: () => void;
  onRenamed: (result: RenameResult) => void;
}) {
  if (!props.target) return null;
  return <RenameDialogContent key={`${props.target.kind}:${props.target.id}`} target={props.target}
    onClose={props.onClose} onRenamed={props.onRenamed} />;
}
