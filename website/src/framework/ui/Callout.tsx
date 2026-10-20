import type { ReactNode } from "react";

export function Callout({ tone, children, role }: { tone?: "warn" | "danger"; children: ReactNode; role?: string }) {
  return (
    <div className={`fw-callout${tone ? " " + tone : ""}`} role={role}>
      {children}
    </div>
  );
}
