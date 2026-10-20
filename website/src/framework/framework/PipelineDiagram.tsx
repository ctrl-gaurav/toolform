import type { KeyboardEvent } from "react";

/* The pipeline, drawn by hand in SVG. Hairline strokes, labels in mono, the
 * accent only on the path a request takes. Each stage node is focusable and
 * jumps to its section below. */

type Node = { id: string; x: number; y: number; w: number; h: number; title: string; sub: string; key?: boolean; stage?: string };

const NODES: Node[] = [
  { id: "ir", x: 196, y: 128, w: 120, h: 64, title: "Canonical IR", sub: "ToolIR", key: true, stage: "load" },
  { id: "evidence", x: 196, y: 16, w: 120, h: 56, title: "Study tables", sub: "evidence JSON" },
  { id: "advisor", x: 356, y: 16, w: 140, h: 56, title: "Advisor", sub: "format + protocol", key: true, stage: "recommend" },
  { id: "render", x: 536, y: 128, w: 116, h: 64, title: "Render", sub: "129 formats", key: true, stage: "render" },
  { id: "model", x: 690, y: 128, w: 118, h: 64, title: "Model", sub: "any endpoint" },
  { id: "parse", x: 846, y: 128, w: 124, h: 64, title: "Parse, validate", sub: "3 grading rules", key: true, stage: "parse" },
  { id: "exec", x: 1004, y: 128, w: 100, h: 64, title: "Execute", sub: "executors", stage: "run" },
];
const INPUTS = ["OpenAI JSON", "MCP tools/list", "Python module", "TypeScript"];

function go(stage?: string) {
  if (!stage) return;
  document.getElementById(`stage-${stage}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}
const onKey = (stage?: string) => (e: KeyboardEvent) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    go(stage);
  }
};

function Box({ n }: { n: Node }) {
  const interactive = !!n.stage;
  return (
    <g
      className={`node${n.key ? " key" : ""}`}
      role={interactive ? "link" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-label={interactive ? `${n.title}: go to the ${n.stage} stage` : undefined}
      onClick={() => go(n.stage)}
      onKeyDown={onKey(n.stage)}
      style={{ cursor: interactive ? "pointer" : "default" }}
    >
      <rect x={n.x} y={n.y} width={n.w} height={n.h} rx="8" />
      <text className="t" x={n.x + 12} y={n.y + 26}>
        {n.title}
      </text>
      <text x={n.x + 12} y={n.y + 46}>
        {n.sub}
      </text>
    </g>
  );
}

export function PipelineDiagram() {
  const arrow = (id: string, hot: boolean) => (
    <marker id={id} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L8,4 L0,8 z" className={`arrow${hot ? " hot" : ""}`} />
    </marker>
  );
  return (
    <div style={{ overflowX: "auto" }} role="figure" aria-label="The ToolForm pipeline: tools are loaded into one IR, pass the guard and the catalogue planner, are rendered in the format and protocol the advisor picks from the study's tables, sent to the model, and the reply is parsed, validated and executed, in a loop.">
      <svg className="fw-diagram" viewBox="0 0 1120 330" style={{ minWidth: 900 }} aria-hidden="false">
        <defs>
          {arrow("fw-a", false)}
          {arrow("fw-a-hot", true)}
        </defs>

        {/* inputs */}
        <text x="16" y="34" style={{ fontSize: 11, letterSpacing: "0.08em" }}>
          TOOLS IN
        </text>
        {INPUTS.map((label, i) => {
          const y = 48 + i * 58;
          return (
            <g key={label}>
              <g className="node" role="link" tabIndex={0} aria-label={`${label}: go to the load stage`} onClick={() => go("load")} onKeyDown={onKey("load")} style={{ cursor: "pointer" }}>
                <rect x="16" y={y} width="140" height="36" rx="6" />
                <text x="28" y={y + 23}>
                  {label}
                </text>
              </g>
              <path className="edge" d={`M156,${y + 18} C176,${y + 18} 176,160 196,160`} markerEnd="url(#fw-a)" />
            </g>
          );
        })}

        {/* gate: guard and catalogue */}
        <g className="gate">
          <rect x="356" y="112" width="140" height="96" rx="10" />
        </g>
        <text x="366" y="104" style={{ fontSize: 11, letterSpacing: "0.08em" }}>
          GATES
        </text>
        <g className="node key" role="link" tabIndex={0} aria-label="Guard: go to the guard stage" onClick={() => go("guard")} onKeyDown={onKey("guard")} style={{ cursor: "pointer" }}>
          <rect x="368" y="122" width="116" height="34" rx="6" />
          <text className="t" x="380" y="144">
            Guard
          </text>
        </g>
        <g className="node key" role="link" tabIndex={0} aria-label="Catalogue: go to the catalogue stage" onClick={() => go("catalogue")} onKeyDown={onKey("catalogue")} style={{ cursor: "pointer" }}>
          <rect x="368" y="164" width="116" height="34" rx="6" />
          <text className="t" x="380" y="186">
            Catalogue
          </text>
        </g>

        {/* edges on the request path */}
        <path className="edge hot" d="M316,160 L356,160" markerEnd="url(#fw-a-hot)" />
        <path className="edge hot" d="M496,160 L536,160" markerEnd="url(#fw-a-hot)" />
        <path className="edge hot" d="M652,160 L690,160" markerEnd="url(#fw-a-hot)" />
        <path className="edge hot" d="M808,160 L846,160" markerEnd="url(#fw-a-hot)" />
        <path className="edge hot" d="M970,160 L1004,160" markerEnd="url(#fw-a-hot)" />
        {/* evidence to advisor, advisor to render */}
        <path className="edge" d="M316,44 L356,44" markerEnd="url(#fw-a)" />
        <path className="edge hot" d="M496,44 C560,44 594,70 594,128" markerEnd="url(#fw-a-hot)" />
        {/* the loop: a tool result goes back to the model */}
        <path className="edge" d="M1054,192 C1054,270 749,270 749,192" markerEnd="url(#fw-a)" />
        <text x="828" y="286">
          tool result, next step (CallLoop)
        </text>
        {/* measurement: eight formats on your endpoint feed the advisor */}
        <path className="edge" d="M749,128 C749,60 640,30 496,30" strokeDasharray="4 4" markerEnd="url(#fw-a)" />
        <text x="620" y="22">
          ab-test: measure eight formats
        </text>

        {NODES.map((n) => (
          <Box key={n.id} n={n} />
        ))}
      </svg>
    </div>
  );
}
