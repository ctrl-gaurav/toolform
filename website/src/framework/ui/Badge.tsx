import type { ReactNode } from "react";

export function Badge({ tone, children, dot, title }: { tone?: "accent" | "ok" | "warn" | "high" | "medium" | "low"; children: ReactNode; dot?: boolean; title?: string }) {
  return (
    <span className={`fw-badge${tone ? " " + tone : ""}`} title={title}>
      {dot && <span className="dot" aria-hidden="true" />}
      {children}
    </span>
  );
}
