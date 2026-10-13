import type { ReactNode } from "react";
import DashboardShell from "@/components/layout/DashboardShell";

export default function AccountPageLayout({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <DashboardShell>
      <section className="mx-auto w-full max-w-4xl p-4 sm:p-8">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{title}</h1>
          <p className="mt-2 text-sm text-muted">{description}</p>
        </div>
        {children}
      </section>
    </DashboardShell>
  );
}
