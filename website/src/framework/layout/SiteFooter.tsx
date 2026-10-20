import { Link } from "react-router-dom";
import { Wordmark } from "../brand/Wordmark";
import { docs, GITHUB, PYPI } from "../lib/links";

export function SiteFooter() {
  return (
    <footer className="fw-footer">
      <div className="wrap">
        <div className="cols">
          <div>
            <Wordmark size={20} />
            <p className="muted" style={{ marginTop: 14, fontSize: 14 }}>
              Tool interfaces, chosen by measurement. An open-source framework built on a controlled study of 129 formats, 31 answer protocols and
              112 models.
            </p>
          </div>
          <nav aria-label="Framework">
            <h2>Framework</h2>
            <ul>
              <li><Link to="/framework">How it works</Link></li>
              <li><a href={docs("quickstart")}>Quick start</a></li>
              <li><a href={docs()}>Documentation</a></li>
              <li><a href={`${GITHUB}/blob/main/CHANGELOG.md`} target="_blank" rel="noreferrer">Changelog</a></li>
            </ul>
          </nav>
          <nav aria-label="Dashboard">
            <h2>Dashboard</h2>
            <ul>
              <li><Link to="/dashboard/advisor">Advisor</Link></li>
              <li><Link to="/dashboard/playground">Playground</Link></li>
              <li><Link to="/dashboard/guard">Guard</Link></li>
              <li><Link to="/dashboard/evidence">Evidence</Link></li>
            </ul>
          </nav>
          <nav aria-label="Project">
            <h2>Project</h2>
            <ul>
              <li><a href={PYPI} target="_blank" rel="noreferrer">PyPI</a></li>
              <li><span className="muted">Paper (coming soon)</span></li>
              <li><a href={GITHUB} target="_blank" rel="noreferrer">GitHub</a></li>
              <li><a href={`${GITHUB}/blob/main/LICENSE`} target="_blank" rel="noreferrer">License: Apache-2.0</a></li>
            </ul>
          </nav>
        </div>
        <div className="note">
          <span>Every number on this site comes from the study's tables.</span>
          <span className="mono">toolform 0.0.1</span>
        </div>
      </div>
    </footer>
  );
}
