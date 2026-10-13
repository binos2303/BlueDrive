type LoadingStateProps = {
  label?: string;
  className?: string;
};

export default function LoadingState({
  label = "Loading",
  className = "",
}: LoadingStateProps) {
  return (
    <div role="status" aria-label={label} className={`flex items-center gap-3 text-sm text-muted ${className}`}>
      <span aria-hidden="true" className="h-5 w-5 animate-spin rounded-full border-2 border-brand-contrast border-r-transparent" />
      <span>{label}...</span>
    </div>
  );
}
