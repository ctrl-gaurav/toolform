import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Wordmark } from "../brand/Wordmark";
import { NavLinks } from "./NavLinks";
import { ThemeToggle } from "./ThemeToggle";

export function SiteHeader() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  return (
    <header className="fw-header">
      <div className="wrap">
        <Link to="/" className="fw-brandlink" aria-label="ToolForm home">
          <Wordmark size={22} />
        </Link>
        <button
          type="button"
          className="fw-iconbtn fw-menubtn"
          aria-expanded={open}
          aria-controls="fw-primary-nav"
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "Close" : "Menu"}
        </button>
        <nav id="fw-primary-nav" className={`fw-nav${open ? " open" : ""}`} aria-label="Primary">
          <NavLinks onNavigate={() => setOpen(false)} />
        </nav>
        <ThemeToggle />
      </div>
    </header>
  );
}
