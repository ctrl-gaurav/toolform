/* The ToolForm site: the landing page, how the framework works, and the dashboard. The documentation is
 * a separate site under /docs/. HashRouter (main.tsx) because GitHub Pages serves static files from a
 * subpath and cannot route on the server. */

import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { SiteShell } from "./framework/layout/SiteShell";
import Landing from "./framework/pages/Landing";

const Framework = lazy(() => import("./framework/pages/Framework"));
const Dashboard = lazy(() => import("./framework/pages/Dashboard"));
const NotFound = lazy(() => import("./framework/pages/NotFound"));

function Loading() {
  return (
    <div className="wrap" style={{ padding: "64px 24px" }} aria-busy="true">
      <p className="muted">Loading.</p>
    </div>
  );
}

const lazyPage = (el: React.ReactNode) => <Suspense fallback={<Loading />}>{el}</Suspense>;

export default function App() {
  return (
    <Routes>
      <Route element={<SiteShell />}>
        <Route index element={<Landing />} />
        <Route path="framework" element={lazyPage(<Framework />)} />
        <Route path="dashboard" element={<Navigate replace to="/dashboard/advisor" />} />
        <Route path="dashboard/:panel" element={lazyPage(<Dashboard />)} />
        <Route path="*" element={lazyPage(<NotFound />)} />
      </Route>
    </Routes>
  );
}
