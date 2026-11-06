import type { ReactNode } from "react";

/** One consistent page heading per Admin route; the app bar is for global tools. */
export default function AdminPageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold tracking-tight text-foreground sm:text-[24px]">{title}</h1>
        {description && <p className="mt-1 text-[13px] leading-5 text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
