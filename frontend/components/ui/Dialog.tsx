import type { ReactNode } from "react";

export default function Dialog({ children }: { children: ReactNode }) {
  return <dialog open>{children}</dialog>;
}
