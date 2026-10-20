import type { ReactNode } from "react";

/* The seven stages, each with a line icon drawn here (no icon library). */

const I = (d: ReactNode) => (
  <svg width="28" height="28" viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {d}
  </svg>
);

export const STAGES: { id: string; n: string; title: string; text: string; module: string; icon: ReactNode }[] = [
  {
    id: "load",
    n: "01",
    title: "Load",
    text: "OpenAI, Anthropic or MCP JSON, a Python module or a TypeScript file, into one canonical IR.",
    module: "toolform.sdk.Toolset",
    icon: I(<><path d="M5 7h10M5 12h14M5 17h8" /><path d="M20 15l3 3-3 3" /><path d="M16 18h7" /></>),
  },
  {
    id: "recommend",
    n: "02",
    title: "Recommend",
    text: "A format and answer protocol from the study's per-factor tables for your model, tool count and tier.",
    module: "toolform.advisor",
    icon: I(<><path d="M4 22V14M10 22V9M16 22V12M22 22V5" /><path d="M20 5h4v4" /></>),
  },
  {
    id: "render",
    n: "03",
    title: "Render",
    text: "The tool block in any of 129 formats and the instruction of any of 31 protocols.",
    module: "toolform.sdk.render",
    icon: I(<><path d="M9 7l-5 7 5 7M19 7l5 7-5 7" /><path d="M16 5l-4 18" /></>),
  },
  {
    id: "parse",
    n: "04",
    title: "Parse",
    text: "The strict parser of the protocol, one of three grading rules, and argument validation.",
    module: "toolform.sdk.parse_reply",
    icon: I(<><rect x="4" y="5" width="20" height="18" rx="2" /><path d="M8 11l3 3 7-7" /><path d="M8 18h12" /></>),
  },
  {
    id: "guard",
    n: "05",
    title: "Guard",
    text: "Flags and strips instructions hidden in third-party tool descriptions.",
    module: "toolform.guard",
    icon: I(<><path d="M14 3l9 4v6c0 6-4 10-9 12-5-2-9-6-9-12V7z" /><path d="M10 14l3 3 5-6" /></>),
  },
  {
    id: "catalogue",
    n: "06",
    title: "Catalogue",
    text: "One shot, retrieval, or names first and one schema second, by tool count.",
    module: "toolform.catalogue",
    icon: I(<><rect x="4" y="4" width="8" height="8" rx="1.5" /><rect x="16" y="4" width="8" height="8" rx="1.5" /><rect x="4" y="16" width="8" height="8" rx="1.5" /><path d="M16 20h8M20 16v8" /></>),
  },
  {
    id: "run",
    n: "07",
    title: "Run",
    text: "A call loop against vLLM, OpenAI or Anthropic, with tracing and cost accounting.",
    module: "toolform.sdk.CallLoop",
    icon: I(<><path d="M22 10a9 9 0 1 0 1 6" /><path d="M23 4v6h-6" /><path d="M12 11l5 3-5 3z" /></>),
  },
];

export function PipelineRail() {
  return (
    <ol className="fw-rail" aria-label="The seven stages of the framework">
      {STAGES.map((s) => (
        <li key={s.id}>
          {s.icon}
          <div>
            <div className="label" style={{ marginBottom: 4 }}>
              <b>{s.n}</b> / {s.title.toUpperCase()}
            </div>
            <p>{s.text}</p>
            <code>{s.module}</code>
          </div>
        </li>
      ))}
    </ol>
  );
}
