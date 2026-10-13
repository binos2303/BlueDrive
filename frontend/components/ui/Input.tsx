import type { InputHTMLAttributes } from "react";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  invalid?: boolean;
};

export default function Input({
  invalid,
  "aria-invalid": ariaInvalid,
  className = "",
  ...props
}: InputProps) {
  const isInvalid = invalid || ariaInvalid === true || ariaInvalid === "true";

  return (
    <input
      {...props}
      aria-invalid={isInvalid || undefined}
      className={`min-h-10 w-full rounded-[var(--radius-control)] border bg-surface px-3 text-sm text-foreground transition-colors duration-[var(--motion-fast)] placeholder:text-muted disabled:cursor-not-allowed disabled:bg-background disabled:opacity-60 ${
        isInvalid
          ? "border-danger focus-visible:outline-danger"
          : "border-border-strong hover:border-muted focus-visible:border-brand-contrast"
      } ${className}`}
    />
  );
}
