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
      <table {...props} className={`w-full border-collapse text-left text-sm ${className}`}>
        {children}
      </table>
    </div>
  );
}
