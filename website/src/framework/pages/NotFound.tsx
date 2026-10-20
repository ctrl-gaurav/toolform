import { Link, useLocation } from "react-router-dom";
import { Logo } from "../brand/Logo";
import { useTitle } from "../layout/SiteShell";
import { docs } from "../lib/links";

export default function NotFound() {
  const loc = useLocation();
  useTitle("Not found");
  return (
    <div className="wrap" style={{ padding: "96px 24px", maxWidth: 720 }}>
      <Logo size={40} />
      <div className="label" style={{ marginTop: 24 }}>
        <b>404</b> / NOT FOUND
      </div>
      <h1 style={{ fontSize: 40, margin: "12px 0" }}>Nothing at this address</h1>
      <p className="muted">
        There is no page at <code>{loc.pathname}</code>.
      </p>
      <ul className="fw-list-plain" style={{ marginTop: 24 }}>
        <li>
          <Link to="/">The framework home</Link>
        </li>
        <li>
          <a href={docs()}>The documentation</a>
        </li>
      </ul>
    </div>
  );
}
