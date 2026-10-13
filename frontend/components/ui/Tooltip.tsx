import { cloneElement, isValidElement, useId, type ReactElement } from "react";

type TooltipProps = {
  content: string;
  children: ReactElement<{ "aria-describedby"?: string }>;
};

export default function Tooltip({ content, children }: TooltipProps) {
  const id = useId();
  const describedBy = [children.props["aria-describedby"], id]
    .filter(Boolean)
    .join(" ");
  const trigger = isValidElement(children)
    ? cloneElement(children, { "aria-describedby": describedBy })
    : children;

  return (
    <span className="group/tooltip relative inline-flex">
      {trigger}
      <span
        id={id}
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-40 mb-2 w-max max-w-56 -translate-x-1/2 rounded-lg bg-brand-dark px-2.5 py-1.5 text-xs text-white opacity-0 shadow-sm transition-opacity duration-[var(--motion-fast)] group-hover/tooltip:opacity-100 group-focus-within/tooltip:opacity-100"
      >
        {content}
      </span>
    </span>
  );
}
