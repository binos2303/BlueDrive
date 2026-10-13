import type { ReactNode } from "react";

type BadgeProps = {
  children: ReactNode;
  variant?: "neutral" | "brand" | "success" | "warning" | "danger";
  className?: string;
};

const variants = {
  neutral: "bg-background text-foreground",
  brand: "bg-brand-soft text-brand-contrast",
  success: "bg-green-50 text-success",
  warning: "bg-amber-50 text-warning",
  danger: "bg-rose-50 text-danger",
};

export default function Badge({
  children,
  variant = "neutral",
  className = "",
}: BadgeProps) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${variants[variant]} ${className}`}>
      {children}
    </span>
  );
}
