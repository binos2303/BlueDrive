import type { TableHTMLAttributes } from "react";

type DataTableProps = TableHTMLAttributes<HTMLTableElement> & {
  children: React.ReactNode;
};

export default function DataTable({
  children,
  className = "",
  ...props
}: DataTableProps) {
  return (
    <div className="w-full overflow-x-auto rounded-xl border border-border bg-surface">
      <table {...props} className={`w-full border-collapse text-left text-sm [&_th]:px-5 [&_th]:py-3 [&_td]:px-5 [&_td]:py-3 [&_td]:align-middle ${className}`}>
        {children}
      </table>
    </div>
  );
}
