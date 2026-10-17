import Link from "next/link";

export type BreadcrumbItem = {
  label: string;
  href?: string;
  onSelect?: () => void;
};

type BreadcrumbProps = {
  items: BreadcrumbItem[];
  className?: string;
  dropTargetIndex?: number | null;
  onItemDragOver?: (event: React.DragEvent<HTMLElement>, index: number) => void;
  onItemDragLeave?: (event: React.DragEvent<HTMLElement>, index: number) => void;
  onItemDrop?: (event: React.DragEvent<HTMLElement>, index: number) => void;
};

export default function Breadcrumb({
  items,
  className = "",
  dropTargetIndex = null,
  onItemDragOver,
  onItemDragLeave,
  onItemDrop,
}: BreadcrumbProps) {
  return (
    <nav aria-label="Breadcrumb" className={className}>
      <ol className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
        {items.map((item, index) => {
          const current = index === items.length - 1;
          return (
            <li
              key={`${item.label}-${index}`}
              onDragOver={onItemDragOver ? (event) => onItemDragOver(event, index) : undefined}
              onDragLeave={onItemDragLeave ? (event) => onItemDragLeave(event, index) : undefined}
              onDrop={onItemDrop ? (event) => onItemDrop(event, index) : undefined}
              data-breadcrumb-drop-target={dropTargetIndex === index ? "true" : undefined}
              className={`flex min-w-0 items-center gap-2 rounded-md transition-colors duration-150 ${dropTargetIndex === index ? "bg-brand-soft ring-2 ring-brand-contrast/50" : ""}`}
            >
              {index > 0 && <span aria-hidden="true" className="text-muted">/</span>}
              {current ? (
                <span
                  aria-current={current ? "page" : undefined}
                  className={`truncate ${current ? "font-medium text-foreground" : "text-muted"}`}
                >
                  {item.label}
                </span>
              ) : item.onSelect ? (
                <button
                  type="button"
                  onClick={item.onSelect}
                  className="truncate text-muted transition-colors duration-(--motion-fast) hover:text-brand-contrast"
                >
                  {item.label}
                </button>
              ) : !item.href ? (
                <span className="truncate text-muted">{item.label}</span>
              ) : (
                <Link
                  href={item.href}
                  className="truncate text-muted transition-colors duration-(--motion-fast) hover:text-brand-contrast"
                >
                  {item.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
