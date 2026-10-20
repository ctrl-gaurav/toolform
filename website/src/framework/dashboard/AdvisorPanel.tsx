import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DEFAULT_SITUATION, recommend, type Recommendation, type Situation } from "../lib/advisor";
import { api, useApi } from "../lib/api";
import { useAdvisorEvidence } from "../lib/evidence";
import { CORE_FORMATS } from "../lib/render";
import { Callout } from "../ui/Callout";
import { AdvisorForm } from "./AdvisorForm";
import { RecommendationCard, type FormatBar } from "./RecommendationCard";
import { parseToolsText, type ToolsValue } from "./ToolsInput";

export function AdvisorPanel() {
  const { evidence, loading } = useAdvisorEvidence();
  const { base, status } = useApi();
  const [params] = useSearchParams();
  const [s, setS] = useState<Situation>(() => ({
    ...DEFAULT_SITUATION,
    model: params.get("model") ?? (params.get("family") ? null : "Qwen/Qwen3-8B"),
    family: params.get("family"),
    n_tools: Number(params.get("n")) || 8,
  }));
  const [tools, setTools] = useState<ToolsValue>(parseToolsText(""));
  const [useTools, setUseTools] = useState(false);
  const set = (patch: Partial<Situation>) => setS((x) => ({ ...x, ...patch }));
  const activeTools = useTools && tools.loaded ? tools.loaded.tools : null;

  // Offline: the browser computes it. Always computed, so the page never waits.
  const local = useMemo<{ rec: Recommendation | null; error: string | null }>(() => {
    if (!evidence) return { rec: null, error: null };
    try {
      const input: Partial<Situation> = { ...s };
      if (activeTools) {
        delete (input as Record<string, unknown>).n_tools;
        delete (input as Record<string, unknown>).tier;
      }
      return { rec: recommend(evidence, input, activeTools), error: null };
    } catch (e) {
      return { rec: null, error: (e as Error).message };
    }
  }, [evidence, s, activeTools]);

  const bars = useMemo<FormatBar[]>(() => {
    if (!evidence || !local.rec) return [];
    return CORE_FORMATS.map((f) => {
      try {
        const r = recommend(evidence, { ...local.rec!.situation, candidates: [f], token_budget: null }, activeTools);
        return { format_id: f, protocol_id: r.protocol_id, expected: r.expected_accuracy, interval: r.interval };
      } catch {
        return { format_id: f, protocol_id: "", expected: 0, interval: null };
      }
    });
  }, [evidence, local.rec, activeTools]);

  // Online: ask toolform serve, and show its answer when it comes.
  const [remote, setRemote] = useState<{ rec: Recommendation | null; error: string | null }>({ rec: null, error: null });
  useEffect(() => {
    if (status !== "online") {
      setRemote({ rec: null, error: null });
      return;
    }
    let alive = true;
    const t = window.setTimeout(() => {
      const situation = { ...s, ...(activeTools ? { n_tools: undefined, tier: undefined } : {}) } as Situation;
      api
        .recommend(base, situation, activeTools ? { source: "auto", payload: JSON.parse(tools.text) } : null)
        .then((rec) => alive && setRemote({ rec, error: null }))
        .catch((e) => alive && setRemote({ rec: null, error: (e as Error).message }));
    }, 250);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [status, base, s, activeTools, tools.text]);

  const shown = remote.rec ?? local.rec;
  const source = remote.rec ? `from toolform serve at ${base}` : `computed in your browser from evidence ${evidence?.version ?? ""}`;

  return (
    <div className="fw-split">
      <aside className="fw-card" aria-label="Inputs">
        <AdvisorForm
          s={s}
          set={set}
          zoo={evidence?.zoo ?? null}
          families={evidence?.families.rows ?? []}
          tiers={evidence?.tiers ?? null}
          tools={tools}
          setTools={setTools}
          useTools={useTools}
          setUseTools={setUseTools}
        />
      </aside>
      <section aria-label="Recommendation" aria-live="polite">
        {loading && <p className="muted">Loading the evidence files.</p>}
        {!loading && !evidence && (
          <Callout tone="danger">
            <p>
              <strong>The evidence files did not load.</strong> They live in <code>data/framework/</code> next to this page; <code>npm run sync</code> copies them from
              the package.
            </p>
          </Callout>
        )}
        {remote.error && (
          <div style={{ marginBottom: 16 }}>
            <Callout tone="warn">
              <p>The API answered with an error, so this is the browser's result: {remote.error}</p>
            </Callout>
          </div>
        )}
        {local.error && !remote.rec && (
          <Callout tone="warn">
            <p>{local.error}</p>
          </Callout>
        )}
        {shown && <RecommendationCard rec={shown} source={source} bars={bars} />}
      </section>
    </div>
  );
}
