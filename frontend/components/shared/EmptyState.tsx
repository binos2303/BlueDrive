import type { ReactNode } from "react";

type EmptyStateProps = {
  title?: string;
  description?: string;
  action?: ReactNode;
};

export default function EmptyState({
  title = "Nothing here yet",
  description = "Items you add will appear here.",
  action,
}: EmptyStateProps) {
  return (
    <section className="flex min-h-48 flex-col items-center justify-center px-5 py-10 text-center" aria-label={title}>
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      <p className="mt-2 max-w-sm text-sm text-muted">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </section>
  );
}
