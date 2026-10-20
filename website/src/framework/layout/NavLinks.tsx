import { NavLink } from "react-router-dom";
import { DOCS, GITHUB } from "../lib/links";

export { GITHUB };

export const NAV_ITEMS = [
  { to: "/framework", label: "Framework" },
  { to: "/dashboard", label: "Dashboard" },
];

export function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      {NAV_ITEMS.map((n) => (
        <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : undefined)} onClick={onNavigate}>
          {n.label}
        </NavLink>
      ))}
      <a href={DOCS} onClick={onNavigate}>
        Docs
      </a>
      <a href={GITHUB} className="ext" target="_blank" rel="noreferrer">
        GitHub
      </a>
    </>
  );
}
