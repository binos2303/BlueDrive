import { X } from "lucide-react";
import type { ReactNode } from "react";
import IconButton from "@/components/ui/IconButton";

type ToastProps = {
  title: string;
  children?: ReactNode;
  variant?: "success" | "warning" | "error" | "info";
  onDismiss?: () => void;
};

const variants = {
  success: "border-success/30 bg-success-soft text-success",
  warning: "border-warning/30 bg-warning-soft text-warning",
  error: "border-danger/30 bg-danger-soft text-danger",
  info: "border-brand/20 bg-brand-soft text-brand-contrast",
};

export default function Toast({
  title,
  children,
  variant = "info",
  onDismiss,
}: ToastProps) {
  return (
    <div
      role={variant === "error" ? "alert" : "status"}
      aria-live={variant === "error" ? "assertive" : "polite"}
      className={`flex items-start gap-3 rounded-xl border p-4 shadow-sm ${variants[variant]}`}
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">{title}</p>
        {children && <div className="mt-1 text-sm">{children}</div>}
      </div>
      {onDismiss && (
        <IconButton label="Dismiss notification" onClick={onDismiss}>
          <X size={17} />
        </IconButton>
      )}
    </div>
  );
}
