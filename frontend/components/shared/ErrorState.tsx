import Button from "@/components/ui/Button";

type ErrorStateProps = {
  title?: string;
  description?: string;
  onRetry?: () => void;
};

export default function ErrorState({
  title = "Something went wrong",
  description = "Please try again.",
  onRetry,
}: ErrorStateProps) {
  return (
    <section role="alert" className="flex flex-col items-center justify-center px-5 py-10 text-center">
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      <p className="mt-2 max-w-sm text-sm text-muted">{description}</p>
      {onRetry && <Button variant="secondary" size="sm" onClick={onRetry} className="mt-5">Try again</Button>}
    </section>
  );
}
