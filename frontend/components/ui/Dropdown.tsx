import type { SelectHTMLAttributes } from "react";

export default function Dropdown({
  className = "",
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={`min-h-10 rounded-[var(--radius-control)] border border-border-strong bg-surface px-3 text-sm text-foreground transition-colors duration-[var(--motion-fast)] hover:border-muted disabled:cursor-not-allowed disabled:bg-background disabled:opacity-60 ${className}`}
    >
      {children}
    </select>
  );
}
