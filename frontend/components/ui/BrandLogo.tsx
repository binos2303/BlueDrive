import { Cloud } from "lucide-react";

export function BrandLogo({ className = "" }: { className?: string }) {
  return (
    <div className={`flex shrink-0 items-center gap-3 ${className}`.trim()}>
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand text-white shadow-sm">
        <Cloud size={20} strokeWidth={2} />
      </span>
      <span className="whitespace-nowrap text-[18px] font-semibold tracking-[-0.02em] text-foreground">BlueDrive</span>
    </div>
  );
}
