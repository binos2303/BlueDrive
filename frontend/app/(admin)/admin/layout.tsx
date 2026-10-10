import type { ReactNode } from "react";
import AdminConsole from "@/components/layout/AdminConsole";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return <AdminConsole>{children}</AdminConsole>;
}
