import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import "../styles/tokens.css";
import "../styles/framework.css";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";

/* Header, main and footer for every framework page. The research pages keep
 * their own layout under /research. */
export function SiteShell() {
  const loc = useLocation();
  useEffect(() => {
    // A new route starts at the top, unless it targets an anchor on the page.
    if (!loc.hash && !loc.search.includes("chart=")) window.scrollTo(0, 0);
  }, [loc.pathname]);
  return (
    <div className="fw">
      <a className="skip" href="#fw-main" onClick={(e) => { e.preventDefault(); document.getElementById("fw-main")?.focus(); }}>
        Skip to content
      </a>
      <SiteHeader />
      <main id="fw-main" tabIndex={-1} style={{ outline: "none" }}>
        <div className="fw-page-in" key={loc.pathname}>
          <Outlet />
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}

export function useTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} | ToolForm` : "ToolForm: tool interfaces, chosen by measurement";
  }, [title]);
}
