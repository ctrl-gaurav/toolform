import { Navigate, useParams } from "react-router-dom";
import { AdvisorPanel } from "../dashboard/AdvisorPanel";
import { DashboardLayout, PANELS } from "../dashboard/DashboardLayout";
import { EvidencePanel } from "../dashboard/EvidencePanel";
import { GuardPanel } from "../dashboard/GuardPanel";
import { PlaygroundPanel } from "../dashboard/PlaygroundPanel";
import { useTitle } from "../layout/SiteShell";

export default function Dashboard() {
  const { panel = "advisor" } = useParams();
  const p = PANELS.find((x) => x.id === panel);
  useTitle(p ? `${p.label}: dashboard` : "Dashboard");
  if (!p) return <Navigate replace to="/dashboard/advisor" />;
  return (
    <DashboardLayout panel={panel}>
      {panel === "advisor" && <AdvisorPanel />}
      {panel === "playground" && <PlaygroundPanel />}
      {panel === "guard" && <GuardPanel />}
      {panel === "evidence" && <EvidencePanel />}
    </DashboardLayout>
  );
}
