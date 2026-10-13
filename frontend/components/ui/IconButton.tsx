import type { ButtonHTMLAttributes, ReactNode } from "react";

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  children: ReactNode;
  variant?: "default" | "destructive";
};

export default function IconButton({
  label,
  children,
  variant = "default",
  className = "",
  type = "button",
  ...props
}: IconButtonProps) {
  return (
    <button
      {...props}
      type={type}
      aria-label={label}
      className={`inline-flex h-10 w-10 items-center justify-center rounded-[var(--radius-control)] transition-colors duration-[var(--motion-fast)] disabled:pointer-events-none disabled:opacity-50 ${
        variant === "destructive"
          ? "text-danger hover:bg-rose-50"
          : "text-muted hover:bg-brand-soft hover:text-brand-contrast"
      } ${className}`}
    >
      {children}
    </button>
  );
}
