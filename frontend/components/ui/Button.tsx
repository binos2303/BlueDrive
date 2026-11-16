import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "destructive";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  children: ReactNode;
};

const variants = {
  primary: "bg-brand-contrast text-on-accent hover:bg-brand-hover",
  secondary: "border border-border-strong bg-surface text-foreground hover:bg-background",
  ghost: "text-muted hover:bg-brand-soft hover:text-brand-contrast",
  destructive: "bg-danger text-on-danger hover:brightness-95",
};

const sizes = {
  sm: "min-h-10 px-3 text-[13px]",
  md: "min-h-11 px-4 text-sm",
  lg: "min-h-12 px-5 text-sm",
};

export default function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  className = "",
  type = "button",
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`ui-control inline-flex shrink-0 items-center justify-center gap-2 rounded-[var(--radius-control)] font-semibold transition-colors duration-[var(--motion-fast)] disabled:pointer-events-none disabled:opacity-50 ${variants[variant]} ${sizes[size]} ${className}`}
    >
      {loading && <span aria-hidden="true" className="h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent motion-reduce:hidden" />}
      {children}
      {loading && <span className="hidden text-xs motion-reduce:inline">Working…</span>}
    </button>
  );
}
