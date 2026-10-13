type ProgressProps = {
  value?: number;
  max?: number;
  label: string;
  className?: string;
};

export default function Progress({
  value,
  max = 100,
  label,
  className = "",
}: ProgressProps) {
  const safeMax = Number.isFinite(max) && max > 0 ? max : 100;
  const safeValue = value === undefined
    ? undefined
    : Math.min(safeMax, Math.max(0, Number.isFinite(value) ? value : 0));
  const percentage = safeValue === undefined ? undefined : (safeValue / safeMax) * 100;

  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={safeMax}
      aria-valuenow={safeValue}
      className={`h-2 overflow-hidden rounded-full bg-border ${className}`}
    >
      <div
        className={`h-full rounded-full bg-brand-contrast transition-[width] duration-[var(--motion-normal)] ${
          percentage === undefined ? "w-1/3 animate-pulse" : ""
        }`}
        style={percentage === undefined ? undefined : { width: `${percentage}%` }}
      />
    </div>
  );
}
