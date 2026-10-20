import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";

type Variant = "primary" | "default" | "ghost";

function cls(variant: Variant, small?: boolean, extra?: string) {
  return ["fw-btn", variant !== "default" ? variant : "", small ? "small" : "", extra ?? ""].filter(Boolean).join(" ");
}

export function Button({ variant = "default", small, className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; small?: boolean }) {
  return <button type="button" className={cls(variant, small, className)} {...rest} />;
}

/** A button-styled link: internal paths go through the router, others are plain anchors. */
export function ButtonLink({ to, variant = "default", small, children, ...rest }: { to: string; variant?: Variant; small?: boolean; children: ReactNode } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  if (/^https?:/.test(to)) {
    return (
      <a href={to} className={cls(variant, small)} target="_blank" rel="noreferrer" {...rest}>
        {children}
      </a>
    );
  }
  return (
    <Link to={to} className={cls(variant, small)}>
      {children}
    </Link>
  );
}
