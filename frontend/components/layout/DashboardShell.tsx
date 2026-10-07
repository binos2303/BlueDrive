import type { ReactNode } from "react";

import Sidebar from "./Sidebar";
import Header from "./Header";

export default function DashboardShell({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <main className="flex h-screen overflow-hidden bg-[#f6f8fb]">
      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        <Header />

        <div className="min-h-0 flex-1 overflow-y-auto">
          {children}
        </div>
      </div>
    </main>
  );
}