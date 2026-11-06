"use client";

import Link from "next/link";
import type { ReactNode } from "react";

type Tab<T extends string> = { value: T; label: string; href?: string; icon?: ReactNode };

export default function AdminSegmentTabs<T extends string>({
  value, tabs, onChange, label,
}: {
  value: T;
  tabs: readonly Tab<T>[];
  onChange?: (value: T) => void;
  label: string;
}) {
  const common = "inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-lg px-3 text-[12px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-contrast";
  return (
    <div className="max-w-full overflow-x-auto pb-1">
      <div aria-label={label} role={onChange ? "tablist" : "group"} className="inline-flex w-max items-center gap-1 rounded-xl bg-background p-1">
        {tabs.map((tab) => {
          const active = value === tab.value;
          const classes = `${common} ${active ? "bg-surface text-brand-contrast shadow-sm" : "text-muted hover:bg-surface/70 hover:text-foreground"}`;
          const content = <>{tab.icon}{tab.label}</>;
          return tab.href
            ? <Link key={tab.value} href={tab.href} aria-current={active ? "page" : undefined} className={classes}>{content}</Link>
            : <button key={tab.value} type="button" role="tab" aria-selected={active} onClick={() => onChange?.(tab.value)} className={classes}>{content}</button>;
        })}
      </div>
    </div>
  );
}
