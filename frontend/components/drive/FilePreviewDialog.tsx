"use client";

import { useEffect, useState } from "react";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";
import {
  fetchDriveFilePreview, getDriveFileDetails, type DriveFileDetails,
} from "@/lib/drive-service";
import { isPreviewSupported, isPreviewSizeAllowed } from "@/lib/file-preview-policy";

export type PreviewFile = { id: number; name: string };

function FilePreviewDialogContent({
  file, onClose, onDownload,
}: {
  file: PreviewFile;
  onClose: () => void;
  onDownload: (file: PreviewFile) => void;
}) {
  const [details, setDetails] = useState<DriveFileDetails | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [contentType, setContentType] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    let objectUrl: string | null = null;
    async function load(fileId: number) {
      try {
        const info = await getDriveFileDetails(fileId);
        if (abort.signal.aborted) return;
        setDetails(info);
        if (!isPreviewSupported(info.mime_type)) {
          setMessage("Preview is not supported for this file type. Download the file instead.");
          return;
        }
        if (!isPreviewSizeAllowed(info.size)) {
          setMessage("This file is too large to preview here. Download it instead.");
          return;
        }
        const blob = await fetchDriveFilePreview(fileId, abort.signal);
        if (abort.signal.aborted) return;
        const mime = blob.type.split(";")[0].toLowerCase();
        setContentType(mime);
        if (mime === "text/plain") {
          const body = await blob.text();
          if (!abort.signal.aborted) setText(body);
        } else {
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        }
      } catch (error) {
        if (!abort.signal.aborted) setMessage(error instanceof Error ? error.message : "Could not preview file.");
      } finally {
        if (!abort.signal.aborted) setLoading(false);
      }
    }
    void load(file.id);
    return () => {
      abort.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [file]);

  return (
    <Dialog open title={file.name} onClose={onClose}
      className="w-[min(100%-2rem,54rem)]">
      <div className="flex max-h-[65vh] min-h-48 flex-col gap-3">
        {loading ? <p role="status" className="py-12 text-center text-sm text-muted">Preparing preview…</p>
          : message ? <p role="alert" className="rounded-lg border border-border p-4 text-sm text-muted">{message}</p>
          : contentType === "text/plain" && text !== null
            ? <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-background p-4 text-sm text-foreground">{text}</pre>
            : url && contentType?.startsWith("image/")
              ? <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto rounded-lg bg-background">
                  {/* Blob is retrieved through the private authenticated Django endpoint. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={url} alt={file?.name ?? "Image preview"} className="max-h-[60vh] max-w-full object-contain" />
                </div>
              : <p className="text-sm text-muted">Preview unavailable.</p>}
        {details && <p className="text-xs text-muted">{details.owner} · {details.access} · {details.size.toLocaleString()} bytes</p>}
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Close</Button>
        {file && <Button onClick={() => onDownload(file)}>Download</Button>}
      </div>
    </Dialog>
  );
}

export default function FilePreviewDialog(props: {
  file: PreviewFile | null;
  onClose: () => void;
  onDownload: (file: PreviewFile) => void;
}) {
  if (!props.file) return null;
  return <FilePreviewDialogContent key={props.file.id} file={props.file}
    onClose={props.onClose} onDownload={props.onDownload} />;
}
