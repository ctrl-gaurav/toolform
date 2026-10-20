import { factMap, useEvidence } from "../lib/evidence";
import { INSTALL } from "../lib/snippets";
import { Wordmark } from "../brand/Wordmark";
import { CodeTabs } from "../landing/CodeTabs";
import { FactStrip } from "../landing/FactStrip";
import { FindingCard } from "../landing/FindingCard";
import { HeroField } from "../landing/HeroField";
import { MiniAdvisor } from "../landing/MiniAdvisor";
import { PipelineRail } from "../landing/PipelineRail";
import { docs, GITHUB, PYPI } from "../lib/links";
import { useTitle } from "../layout/SiteShell";
import { ButtonLink } from "../ui/Button";
import { CopyButton } from "../ui/CopyButton";
import { Link } from "react-router-dom";

function SectionHead({ n, label, title, children }: { n: string; label: string; title: string; children?: React.ReactNode }) {
  return (
    <header>
      <div className="label">
        <b>{n}</b> / {label}
      </div>
      <h2 style={{ fontSize: 34, margin: "12px 0 10px" }}>{title}</h2>
      {children && <p>{children}</p>}
    </header>
  );
}

export default function Landing() {
  useTitle("");
  const { data } = useEvidence("facts");
  const f = factMap(data);
  const n = (id: string, digits = 2) => (f[id] ? f[id].value.toFixed(digits) : "...");
  const sel: [string, string, string][] = [
    ["measure_eight", "measure eight on the target model", "best"],
    ["lookup_count_tier", "best format per count and tier", ""],
    ["always_xml", "always XML", ""],
    ["fitted_rule", "the fitted rule", ""],
    ["always_json", "always JSON Schema (the default)", ""],
  ];

  return (
    <>
      <section className="fw-hero">
        <HeroField />
        <div className="fade" aria-hidden="true" />
        <div className="wrap">
          <div className="inner">
            <Wordmark size={30} />
            <h1>
              Tool interfaces, <span className="accent">chosen by measurement.</span>
            </h1>
            <p className="pitch">
              Every agent shows its tools to a model somehow. ToolForm picks the format and the answer protocol for your model from the per-factor tables
              of a controlled study, renders and parses them, and guards the description channel. Or it measures eight formats on your own endpoint and
              picks the best, which beat every rule we tested.
            </p>
            <div className="ctas">
              <a className="fw-btn primary" href={docs("quickstart")}>
                Get started
              </a>
              <ButtonLink to="/dashboard/advisor">Open the dashboard</ButtonLink>
              <span className="textlinks">
                <a href={PYPI} target="_blank" rel="noreferrer">
                  PyPI
                </a>
                <span className="faint">Paper (coming soon)</span>
                <a href={GITHUB} target="_blank" rel="noreferrer">
                  GitHub
                </a>
              </span>
            </div>
            <div className="fw-install">
              <span className="prompt" aria-hidden="true">
                $
              </span>
              <code>{INSTALL}</code>
              <CopyButton text={INSTALL} />
            </div>
          </div>
        </div>
      </section>

      <FactStrip />

      <section className="fw-section" aria-labelledby="findings">
        <div className="wrap">
          <SectionHead n="01" label="EVIDENCE" title="What the study found">
            Seven results that decide how the framework chooses. Each card opens its chart and names the table it comes from.
          </SectionHead>
          <h2 id="findings" className="sr-only">
            What the study found
          </h2>
          <div className="fw-grid3">
            <FindingCard value={`${n("schema_over_names")}`} unit="%" source="schema ladder" chart="ladder">
              is what the parameter schema is worth over tool names alone. Names let a model pick the tool; the schema lets it write the arguments.
            </FindingCard>
            <FindingCard value={`+${n("xml_minus_json_main")}`} unit="%" source="main table" chart="graders">
              XML leads JSON Schema by {n("xml_minus_json_main")}% under the main grading rule, {n("xml_minus_json_symmetric")}% under the symmetric one, and trails
              by {Math.abs(Number(n("xml_minus_json_as_written"))).toFixed(2)}% as written. The ranking depends on how a reply is graded.
            </FindingCard>
            <FindingCard value={`${n("protocol_ratio_as_written")} to ${n("protocol_ratio_main")}`} unit="x" source="protocol crossing" chart="crossing">
              as much change in accuracy from the answer protocol as from the schema format, across the three grading rules.
            </FindingCard>
            <FindingCard value={`${n("grammar_hallucinated_fixed")}`} unit="%" source="constrained decoding" cta="from the paper">
              hallucinated tool names under a fixed grammar, down from {n("grammar_hallucinated_free")}%. The gap between formats stays.
            </FindingCard>
            <FindingCard value={`${n("injection_min")} to ${n("injection_max")}`} unit="%" source="pressure tests" chart="injection">
              of turns followed an instruction hidden in one tool's description, in every format that shows one. A trust sentence in the system prompt did not lower
              it.
            </FindingCard>
            <FindingCard value={`-${n("tool_count_cost")}`} unit="%" source="tool count" chart="tool-count">
              strict-call accuracy going from 1 tool ({n("tools_1")}%) to 256 ({n("tools_256")}%). At 256 tools, {n("empty_at_256")}% of turns return nothing.
            </FindingCard>
            <FindingCard
              wide
              value={`${n("measure_eight")}`}
              unit="%"
              source="selection rules"
              chart="selection"
              extra={
                <div className="bars" aria-label="Mean accuracy of each selection strategy, families held out">
                  {sel.map(([id, label, best]) => (
                    <div key={id} className={`fw-minibar${best ? " best" : ""}`}>
                      <span>{label}</span>
                      <span className="track" aria-hidden="true">
                        <span className="fill" style={{ display: "block", width: `${f[id] ? f[id].value : 0}%` }} />
                      </span>
                      <span className="n">{n(id)}%</span>
                    </div>
                  ))}
                </div>
              }
            >
              Measuring eight formats on the target model, 400 requests, beat every rule the study tried: {n("measure_eight")}% against {n("fitted_rule")}% for the
              fitted rule and {n("always_json")}% for the JSON Schema default, with each family held out.
            </FindingCard>
          </div>
        </div>
      </section>

      <section className="fw-section" aria-label="What the framework does">
        <div className="wrap">
          <SectionHead n="02" label="PIPELINE" title="What the framework does">
            Seven stages, each a module you can use alone. <Link to="/framework">How each one works.</Link>
          </SectionHead>
          <PipelineRail />
        </div>
      </section>

      <section className="fw-section" aria-label="Use it">
        <div className="wrap">
          <SectionHead n="03" label="USE" title="A Python SDK, a CLI and an HTTP API">
            The same objects everywhere: the CLI's <code>--json</code> flag and the API return what the SDK's <code>to_dict()</code> returns.
          </SectionHead>
          <div className="fw-grid2" style={{ alignItems: "start" }}>
            <CodeTabs />
            <MiniAdvisor />
          </div>
        </div>
      </section>

      <section className="fw-section" aria-label="Research">
        <div className="wrap">
          <SectionHead n="04" label="RESEARCH" title="Built on a controlled study">
            The framework ships the study's renderers, parsers and graders, and its tables as evidence: 100 open-source and 12 proprietary models, 129
            schema formats, 31 answer protocols and 3 grading rules. The paper is coming soon.
          </SectionHead>
          <div className="row">
            <ButtonLink to="/dashboard/evidence">The evidence explorer</ButtonLink>
            <a className="fw-btn ghost" href={docs()}>
              Read the documentation
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
