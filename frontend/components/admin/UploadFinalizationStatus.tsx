import type { UploadOperations } from "@/lib/admin-overview-service";

export default function UploadFinalizationStatus({ data }: { data: UploadOperations | undefined }) {
  const rows = [
    ["Queued jobs", data?.pending_jobs],
    ["Processing jobs", data?.processing_jobs],
    ["Failed jobs (retained)", data?.failed_jobs],
    ["Stale processing jobs", data?.stale_processing_jobs],
    ["Uploads verifying", data?.verifying_uploads],
    ["Uploads scanning", data?.scanning_uploads],
  ] as const;
  const oldest = data?.oldest_active_job_at ? new Date(data.oldest_active_job_at) : null;
  return <section className="overflow-hidden rounded-[20px] border border-border bg-surface" aria-labelledby="upload-processing-title">
    <div className="border-b border-border px-5 py-4">
      <h2 id="upload-processing-title" className="text-sm font-semibold">Upload processing</h2>
      <p className="mt-1 text-xs leading-5 text-muted">Database job records. Stale means no update for more than 10 minutes; it does not prove that a worker is offline.</p>
    </div>
    {data && data.stale_processing_jobs > 0 && <p role="status" className="border-b border-border px-5 py-3 text-sm text-danger">Stale upload processing needs attention.</p>}
    <dl className="divide-y divide-border/60">
      {rows.map(([label, value]) => <div key={label} className="flex items-center justify-between gap-4 px-5 py-3 text-[13px]">
        <dt className="text-muted">{label}</dt><dd className="font-semibold tabular-nums">{value === undefined ? "—" : value.toLocaleString()}</dd>
      </div>)}
      <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 text-[13px]"><dt className="text-muted">Oldest active job update</dt><dd>{!data ? "Not verified" : !oldest ? "No active jobs" : Number.isNaN(oldest.getTime()) ? "Not recorded" : oldest.toLocaleString()}</dd></div>
    </dl>
    <p className="border-t border-border px-5 py-3 text-xs leading-5 text-muted">Failed jobs are retained history, not a count of newly failed uploads. Storage health and backup execution are not monitored here.</p>
  </section>;
}
