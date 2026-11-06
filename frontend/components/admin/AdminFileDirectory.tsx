"use client";

import { useEffect, useState, type FormEvent } from "react";
import {
  Archive, ChevronLeft, ChevronRight, File as FileIcon, FileImage, FileMusic,
  FileText, FileVideo, FolderOpen, HardDrive, LockKeyhole,
  RefreshCw, Search, X,
} from "lucide-react";
import AdminPageHeader from "@/components/admin/AdminPageHeader";
import AdminSegmentTabs from "@/components/admin/AdminSegmentTabs";
import Dialog from "@/components/ui/Dialog";
import styles from "./AdminFileDirectory.module.css";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

type Scope = "all" | "my_drive" | "workspace" | "organization";
type Lifecycle = "active" | "trash" | "all";
type FileType = "all" | "document" | "image" | "video" | "audio" | "archive" | "other";
type Sort = "newest" | "updated" | "name" | "largest" | "oldest";
type FileRow = {
  id: number;
  name: string;
  size_bytes: number;
  mime_type: string;
  owner: { id: number; username: string };
  scope: "my_drive" | "workspace" | "organization";
  organization: { id: string; name: string } | null;
  workspace: { id: string; name: string };
  folder: { id: number; name: string } | null;
  lifecycle: "active" | "trash";
  version_state: string | null;
  current_version: number | null;
  version_count: number | null;
  is_encrypted: boolean;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};
type FileVersion = {
  id: string;
  number: number;
  state: string;
  is_current: boolean;
  size_bytes: number;
  mime_type: string;
  created_at: string;
  verified_at: string | null;
  storage: { provider: string; state: string; verified_at: string | null }[];
};
type FileDetail = FileRow & {
  last_accessed_at: string | null;
  purge_after: string | null;
  versions: FileVersion[];
  versions_limit: number;
};
type Directory = {
  count: number;
  page: number;
  page_size: number;
  summary: { active: number; trash: number; active_metadata_bytes: number };
  results: FileRow[];
};

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB", "PB"];
  let size = value / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit++; }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unit]}`;
}
function formatDate(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function formatState(value: string | null) {
  return value ? value.replaceAll("_", " ") : "No version metadata";
}
function iconForFile(file: FileRow) {
  const name = file.name.toLowerCase();
  if (file.mime_type.startsWith("image/") || /\.(png|jpe?g|gif|webp|svg)$/.test(name)) return FileImage;
  if (file.mime_type.startsWith("video/") || /\.(mp4|mov|webm|avi)$/.test(name)) return FileVideo;
  if (file.mime_type.startsWith("audio/") || /\.(mp3|wav|ogg|flac)$/.test(name)) return FileMusic;
  if (/\.(zip|7z|rar|tar|gz)$/.test(name)) return Archive;
  if (/\.(pdf|txt|docx?|xlsx?|pptx?|csv|odt|ods)$/.test(name) || file.mime_type.startsWith("text/")) return FileText;
  return FileIcon;
}
function DataField({ label, value }: { label: string; value: string }) {
  return <div className="flex flex-col gap-1 border-b border-border/60 py-3 last:border-0 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
    <dt className="text-xs text-muted">{label}</dt><dd className="wrap-break-word text-[13px] font-medium text-foreground sm:max-w-[65%] sm:text-right">{value}</dd>
  </div>;
}

export default function AdminFileDirectory() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<Scope>("all");
  const [lifecycle, setLifecycle] = useState<Lifecycle>("active");
  const [fileType, setFileType] = useState<FileType>("all");
  const [sort, setSort] = useState<Sort>("newest");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<Directory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<FileDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ q: query, scope, status: lifecycle, type: fileType, sort, page: String(page) });
    fetch(`${apiBase}/accounts/api/admin/files/?${params}`, { credentials: "include", cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 403
          ? "Access denied. Sign in with a Platform Admin account."
          : `Unable to load file inventory (HTTP ${response.status}).`);
        return response.json() as Promise<Directory>;
      })
      .then((result) => { if (!controller.signal.aborted) { setData(result); setError(""); setLoading(false); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted) { setData(null); setError(reason instanceof Error ? reason.message : "File request failed."); setLoading(false); } });
    return () => controller.abort();
  }, [query, scope, lifecycle, fileType, sort, page, revision]);

  useEffect(() => {
    if (selectedId === null) return;
    const controller = new AbortController();
    fetch(`${apiBase}/accounts/api/admin/files/${selectedId}/`, { credentials: "include", cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Unable to load file details (HTTP ${response.status}).`);
        return response.json() as Promise<FileDetail>;
      })
      .then((result) => { if (!controller.signal.aborted) { setDetail(result); setDetailLoading(false); setDetailError(""); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted) { setDetail(null); setDetailLoading(false); setDetailError(reason instanceof Error ? reason.message : "Could not load details."); } });
    return () => controller.abort();
  }, [selectedId]);

  function openFile(id: number) {
    setSelectedId(id);
    setDetail(null);
    setDetailError("");
    setDetailLoading(true);
  }
  function closeFile() { setSelectedId(null); setDetail(null); setDetailError(""); }
  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setQuery(input.trim()); setPage(1); setLoading(true);
    setRevision((r) => r + 1);
  }
  function changeScope(value: Scope) { setScope(value); setPage(1); setLoading(true); }
  function changeStatus(value: Lifecycle) { setLifecycle(value); setPage(1); setLoading(true); }
  function changeType(value: FileType) { setFileType(value); setPage(1); setLoading(true); }
  function changeSort(value: Sort) { setSort(value); setPage(1); setLoading(true); }
  const totalPages = Math.max(1, Math.ceil((data?.count ?? 0) / (data?.page_size || 20)));
  const formatCount = (value: number | undefined) => value === undefined ? "—" : value.toLocaleString("en-US");

  return <div className="space-y-5">
    <AdminPageHeader title="File Management" actions={
      <button type="button" disabled={loading} onClick={() => { setLoading(true); setRevision((r) => r + 1); }} className="inline-flex h-9 items-center gap-2 rounded-xl border border-border bg-surface px-3 text-xs font-medium hover:bg-brand-soft disabled:opacity-50"><RefreshCw size={15} className={loading ? "animate-spin" : ""} />Refresh</button>
    } />

    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {[
        { label: "Active files", value: formatCount(data?.summary.active), description: "Current inventory" },
        { label: "Files in trash", value: formatCount(data?.summary.trash), description: "Soft-deleted metadata" },
        { label: "Active file sizes", value: data ? formatBytes(data.summary.active_metadata_bytes) : "—", description: "Logical size, not disk usage" },
      ].map((item) => <section key={item.label} className="rounded-[20px] border border-border bg-surface px-5 py-4"><p className="text-[12px] text-muted">{item.label}</p><p className="mt-2 text-[25px] font-semibold tabular-nums tracking-tight">{item.value}</p><p className="mt-1 text-[11px] text-muted">{item.description}</p></section>)}
    </div>

    <section className={`${styles.filterContainer} overflow-hidden rounded-[20px] border border-border bg-surface`}>
      <div className="space-y-4 border-b border-border p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <AdminSegmentTabs<Scope> value={scope} label="File ownership scope" onChange={changeScope} tabs={[
            { value: "all", label: "All files" },
            { value: "my_drive", label: "Personal Files" },
            { value: "workspace", label: "Workspaces" },
            { value: "organization", label: "Organizations" },
          ]} />
          <span className="text-xs text-muted">{loading ? "Loading…" : `${formatCount(data?.count)} matching files`}</span>
        </div>
        <div className={styles.filterGrid}>
          <div className={styles.searchField}>
            <label htmlFor="admin-file-search" className="mb-1.5 block text-[12px] text-muted">Search files</label>
            <form data-admin-search-shell role="search" onSubmit={search} className="flex h-11 min-w-0 items-center gap-2.5 rounded-xl border border-border bg-background px-3">
              <Search size={16} className="shrink-0 text-muted" />
              <input
                id="admin-file-search"
                aria-label="Search files, owners, organizations or workspaces"
                placeholder="File, owner, workspace…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                className="min-w-0 w-full flex-1 bg-transparent text-[13px] text-foreground outline-none"
              />
              {input && <button type="button" title="Clear search" aria-label="Clear search" onClick={() => { setInput(""); setQuery(""); setPage(1); setLoading(true); }} className="shrink-0 text-muted hover:text-foreground"><X size={14} /></button>}
              <button type="submit" className="shrink-0 text-xs font-semibold text-brand-contrast">Search</button>
            </form>
          </div>
          <label className="min-w-0 text-[12px] text-muted">
            <span className="mb-1.5 block">Status</span>
            <select aria-label="File status" value={lifecycle} onChange={(e) => changeStatus(e.target.value as Lifecycle)} className="h-11 w-full min-w-0 rounded-xl border border-border bg-background px-3 text-[13px] text-foreground">
              <option value="active">Active</option><option value="trash">In trash</option><option value="all">All statuses</option>
            </select>
          </label>
          <label className="min-w-0 text-[12px] text-muted">
            <span className="mb-1.5 block">File type</span>
            <select aria-label="File type" value={fileType} onChange={(e) => changeType(e.target.value as FileType)} className="h-11 w-full min-w-0 rounded-xl border border-border bg-background px-3 text-[13px] text-foreground">
              <option value="all">All types</option><option value="document">Documents</option><option value="image">Images</option><option value="video">Video</option><option value="audio">Audio</option><option value="archive">Archives</option><option value="other">Other</option>
            </select>
          </label>
          <label className={`${styles.sortField} min-w-0 text-[12px] text-muted`}>
            <span className="mb-1.5 block">Sort by</span>
            <select aria-label="Sort files" value={sort} onChange={(e) => changeSort(e.target.value as Sort)} className="h-11 w-full min-w-0 rounded-xl border border-border bg-background px-3 text-[13px] text-foreground">
              <option value="newest">Newest first</option><option value="updated">Recently updated</option><option value="name">Name A–Z</option><option value="largest">Largest first</option><option value="oldest">Oldest first</option>
            </select>
          </label>
        </div>
      </div>

      {error && <div role="alert" className="m-5 rounded-xl border border-danger/25 px-4 py-3 text-[13px] text-danger"><p className="font-semibold">File inventory unavailable</p><p className="mt-1">{error}</p></div>}
      {loading && <div role="status" className="flex min-h-52 items-center justify-center gap-2 text-[13px] text-muted"><RefreshCw size={16} className="animate-spin" />Loading file metadata…</div>}
      {!loading && !error && <div className="overflow-x-auto">
        <table className="w-full min-w-235 text-left text-[13px]">
          <thead className="bg-background text-[11px] font-medium text-muted"><tr><th className="px-5 py-3">File</th><th className="px-4 py-3">Owner</th><th className="px-4 py-3">Location</th><th className="px-4 py-3">Size</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Modified</th><th className="px-5 py-3 text-right">Details</th></tr></thead>
          <tbody>{data?.results.map((file) => {
            const Icon = iconForFile(file);
            return <tr key={file.id} className="border-t border-border/70 transition-colors hover:bg-background/70">
              <td className="px-5 py-3"><div className="flex min-w-40 max-w-70 items-center gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-contrast"><Icon size={18}/></span><div className="min-w-0"><button type="button" onClick={() => openFile(file.id)} className="block max-w-full truncate text-left font-semibold hover:text-brand-contrast hover:underline" title={file.name}>{file.name}</button><p className="mt-0.5 text-[11px] text-muted">{file.mime_type || "Unknown MIME type"}{file.is_encrypted && <LockKeyhole size={11} className="ml-1 inline align-text-top" aria-label="Encrypted" />}</p></div></div></td>
              <td className="px-4 py-3"><p className="font-medium">{file.owner.username}</p><p className="text-[11px] text-muted">ID {file.owner.id}</p></td>
              <td className="px-4 py-3"><p className="max-w-48 truncate font-medium" title={file.workspace.name}>{file.workspace.name}</p><p className="max-w-48 truncate text-[11px] text-muted" title={file.organization?.name || (file.scope === "my_drive" ? "Personal Files" : "Independent Workspace")}>{file.organization?.name || (file.scope === "my_drive" ? "Personal Files" : "Independent Workspace")}</p></td>
              <td className="whitespace-nowrap px-4 py-3 tabular-nums">{formatBytes(file.size_bytes)}</td>
              <td className="px-4 py-3"><span className={`inline-flex rounded-lg px-2.5 py-1 text-[11px] font-semibold ${file.lifecycle === "active" ? "bg-brand-soft text-brand-contrast" : "bg-background text-muted"}`}>{file.lifecycle === "active" ? "Active" : "In trash"}</span><p className="mt-1.5 text-[11px] capitalize text-muted">{formatState(file.version_state)}</p></td>
              <td className="whitespace-nowrap px-4 py-3 text-[12px] text-muted">{formatDate(file.updated_at)}</td>
              <td className="px-5 py-3 text-right"><button type="button" onClick={() => openFile(file.id)} className="rounded-lg border border-border px-3 py-2 text-[11px] font-semibold transition-colors hover:bg-brand-soft hover:text-brand-contrast" aria-label={`View metadata for ${file.name}`}>View</button></td>
            </tr>;
          })}</tbody>
        </table>
        {data?.results.length === 0 && <div className="flex min-h-44 flex-col items-center justify-center gap-2 p-7 text-center"><FolderOpen size={23} className="text-muted" /><p className="text-sm font-medium">No matching files</p><p className="text-xs text-muted">Try a different search, scope or filter.</p></div>}
      </div>}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3.5 text-xs"><span className="text-muted">Page {page} of {totalPages} · {formatCount(data?.count)} results</span><div className="flex gap-2"><button disabled={page <= 1 || loading} onClick={() => { setPage((n) => n - 1); setLoading(true); }} className="inline-flex h-9 items-center gap-1 rounded-lg border border-border px-3 font-medium disabled:opacity-40"><ChevronLeft size={14}/>Previous</button><button disabled={page >= totalPages || loading} onClick={() => { setPage((n) => n + 1); setLoading(true); }} className="inline-flex h-9 items-center gap-1 rounded-lg border border-border px-3 font-medium disabled:opacity-40">Next<ChevronRight size={14}/></button></div></div>
    </section>


    <Dialog open={selectedId !== null} title={detail?.name || "File details"} description="Administrative metadata · Read-only" onClose={closeFile} className="max-w-165">
      {detailLoading && <p role="status" className="flex items-center gap-2 text-sm text-muted"><RefreshCw size={16} className="animate-spin"/>Loading file details…</p>}
      {detailError && <p role="alert" className="text-sm text-danger">{detailError}</p>}
      {detail && <div className="space-y-5">
        <section><h3 className="mb-2 text-[13px] font-semibold">File metadata</h3><dl><DataField label="File ID" value={String(detail.id)} /><DataField label="Owner" value={`${detail.owner.username} (#${detail.owner.id})`} /><DataField label="Scope" value={detail.scope === "my_drive" ? "Personal Files" : detail.scope === "workspace" ? "Independent Workspace" : "Organization"} /><DataField label="Organization" value={detail.organization?.name || "—"} /><DataField label="Workspace" value={detail.workspace.name} /><DataField label="Folder" value={detail.folder?.name || "Root"} /><DataField label="File type" value={detail.mime_type || "Not recorded"}/><DataField label="File size" value={formatBytes(detail.size_bytes)} /><DataField label="Status" value={detail.lifecycle === "active" ? "Active" : "In trash"}/><DataField label="Current version" value={detail.current_version ? `v${detail.current_version} · ${formatState(detail.version_state)}` : "Not recorded"}/><DataField label="Version history" value={`${detail.version_count} recorded`}/><DataField label="Encrypted" value={detail.is_encrypted ? "Yes" : "No"}/><DataField label="Created" value={formatDate(detail.created_at)}/><DataField label="Modified" value={formatDate(detail.updated_at)}/><DataField label="Last accessed" value={formatDate(detail.last_accessed_at)}/>{detail.deleted_at && <DataField label="Moved to trash" value={formatDate(detail.deleted_at)}/>}</dl></section>
        <section><h3 className="mb-1 flex items-center gap-2 text-[13px] font-semibold"><HardDrive size={16} className="text-brand-contrast"/>Recorded versions & storage</h3><p className="mb-3 text-[11px] text-muted">Latest {detail.versions_limit} versions maximum. Storage entries show logical state only, not physical disk availability.</p>
          {detail.versions.length === 0 ? <div className="rounded-xl border border-border bg-background p-4 text-[12px] text-muted">No file version records are available.</div> : <div className="space-y-2.5">{detail.versions.map((version) => <article key={version.id} className="rounded-xl border border-border bg-background p-3.5"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-[12px] font-semibold">Version {version.number}{version.is_current && <span className="ml-2 rounded-md bg-brand-soft px-2 py-0.5 text-[10px] text-brand-contrast">Current</span>}</p><p className="mt-1 text-[11px] text-muted">{formatDate(version.created_at)} · {formatBytes(version.size_bytes)}</p></div><span className="rounded-lg border border-border px-2 py-1 text-[11px] capitalize">{formatState(version.state)}</span></div><div className="mt-2.5 space-y-1 border-t border-border pt-2.5">{version.storage.length > 0 ? version.storage.map((location, index) => <div key={`${version.id}-${index}`} className="flex items-center justify-between gap-2 text-[11px]"><span className="font-medium uppercase text-foreground">{location.provider}</span><span className="capitalize text-muted">{formatState(location.state)}</span></div>) : <p className="text-[11px] text-muted">No storage location recorded for this version.</p>}</div></article>)}</div>}
        </section>
        <div className="flex items-start gap-2 rounded-xl border border-border bg-background p-3 text-[11px] leading-5 text-muted"><LockKeyhole size={15} className="mt-0.5 shrink-0"/>This console intentionally does not expose file content, encryption keys, storage object identifiers or download links.</div>
      </div>}
    </Dialog>
  </div>;
}
