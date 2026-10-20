import { docs } from "../lib/links";
import { Link } from "react-router-dom";
import { PipelineDiagram } from "../framework/PipelineDiagram";
import { StageSection, type StageInfo } from "../framework/StageSection";
import { useTitle } from "../layout/SiteShell";

const STAGES: StageInfo[] = [
  {
    id: "load",
    n: "01",
    title: "Load",
    module: "toolform.sdk.Toolset",
    what: "Tools arrive in many shapes. ToolForm converts them once into the canonical IR the study rendered every format from: names, descriptions, typed parameters with nesting, enums, constraints and defaults. Every later stage reads the IR, so the format is a rendering choice and nothing else.",
    sdk: `from toolform.sdk import Toolset

tools = Toolset.from_openai("tools/openai_tools.json")   # or from_mcp, from_anthropic, from_ir
py_tools = Toolset.from_python("weather.py")              # executors come with it
print(tools.summary())                                    # n_tools, names, tier_estimate, ...`,
    cli: "toolform convert tools.json --to mcp",
    http: "POST /api/v1/tools/load, POST /api/v1/tools/export",
    evidence: "The same IR carried 24 generated domains and 66 real tool schemas through all 129 formats, so a difference between formats is a difference in rendering.",
  },
  {
    id: "recommend",
    n: "02",
    title: "Recommend",
    module: "toolform.advisor",
    what: (
      <>
        The advisor reads the study's tables for your model family (or pooled checkpoints when the family is unknown), shifts the value for your tool count, tier and
        answer protocol, and returns the format, the protocol, the expected accuracy with the range across the table values it rests on, the token cost and the reason. When you
        can call the model, <code>ab_test</code> measures eight formats on it instead.
      </>
    ),
    sdk: `from toolform.advisor import recommend, ab_test

rec = recommend(model="Qwen/Qwen3-8B", n_tools=8, tier=3)
print(rec.summary())        # format + protocol, expected accuracy and its range
print(rec.explanation)      # every number with its table

report = ab_test(client, n_requests=50)    # 8 formats x 50 generated requests = 400 calls`,
    cli: "toolform recommend --model Qwen/Qwen3-8B --n-tools 8 --tier 3",
    http: "POST /api/v1/recommend, POST /api/v1/ab-test",
    evidence: "Measuring eight formats on the target model reached 69.18%, against 64.35% for the fitted rule and 57.97% for the JSON Schema default, with each family held out (tab_selection).",
  },
  {
    id: "render",
    n: "03",
    title: "Render",
    module: "toolform.sdk.render",
    what: "The tool block in any of the 129 formats, the answer instruction of any of the 31 protocols, and the chat messages assembled exactly as the study assembled them. Rendering options cover descriptions, constraints, defaults, returns, minification and naming convention.",
    sdk: `from toolform.sdk import render, compare_formats

prompt = render(tools, "xml_schema", "xml_call", request="Forecast for Denver, 5 days")
print(prompt.tokens_estimate)       # the tool block, estimated as characters / 4
messages = prompt.messages          # system and user messages
rows = compare_formats(tools)       # tokens of every study format, side by side`,
    cli: "toolform render tools.json --format xml_schema --compare",
    http: "POST /api/v1/render, POST /api/v1/render/compare",
    evidence: "The median open checkpoint varies by 44% across the eight core formats, the median anchor model by 25% (the results section, from tab_models_main).",
  },
  {
    id: "parse",
    n: "04",
    title: "Parse",
    module: "toolform.sdk.parse_reply",
    what: "The reply is read by the protocol's own strict parser, under one of the three grading rules the study used, and every call's arguments are validated and normalised against the schema. The lenient parse is available, and reported as format compliance, not in place of the strict one.",
    sdk: `from toolform.sdk import parse_reply

parsed = parse_reply(reply, tools, "xml_call", rule="main")   # or "symmetric", "as_written"
call = parsed.calls[0]
print(call.resolved_name, call.arguments, call.valid)`,
    cli: "toolform parse tools.json --protocol xml_call --reply-file reply.txt",
    http: "POST /api/v1/parse",
    evidence: "XML leads JSON Schema by 13.80% under the main rule, 1.07% under the symmetric one, and trails by 3.28% as written (tab_main). A human check judged 12.5% of the re-nesting repairs wrong.",
  },
  {
    id: "guard",
    n: "05",
    title: "Guard",
    module: "toolform.guard",
    what: "Third-party tool metadata is a channel into the prompt. The guard scans every description, parameter note, enum value and annotation with nine rules, reports what it finds by severity, and strips the flagged sentences or all descriptions. Names and schemas never change, so calls still resolve. It is a rule-based detector; the study did not measure its detection rate.",
    sdk: `from toolform.guard import guard

report = guard(mcp_tools, strictness="standard", action="strip")
for f in report.findings:
    print(f.severity, f.rule_id, f.tool, f.field, f.text)
safe_tools = report.toolset`,
    cli: "toolform guard mcp_tools.json --strictness standard --fail-on high",
    http: "POST /api/v1/guard",
    evidence: "An instruction hidden in one tool's description was followed on 38.48 to 54.16% of turns in every format that shows one; a trust sentence in the system prompt changed that by -0.35 and +0.23 (tab_pressure, tab_injection_trust).",
  },
  {
    id: "catalogue",
    n: "06",
    title: "Catalogue",
    module: "toolform.catalogue",
    what: "Long tool lists cost accuracy and then stop fitting. The catalogue module plans one shot, retrieval of the top tools for each request, or two-stage disclosure (the names first, one schema second), from the same thresholds the advisor uses, and fits a block to a token budget with a report of what it dropped.",
    sdk: `from toolform.catalogue import plan_catalogue, retrieve, TwoStage

plan = plan_catalogue(tools, context_tokens=32768)     # one_shot, retrieve or two_stage
top = retrieve(tools, "forecast for Denver", k=8)      # BM25
result = TwoStage(tools).run(client, "forecast for Denver")`,
    cli: "toolform catalogue tools.json --query \"forecast for Denver\" --k 8",
    http: "POST /api/v1/catalogue/plan, /catalogue/retrieve, /catalogue/two-stage/prompt",
    evidence: "Going from 1 to 256 tools cost 41.01%. On a 128-tool panel the top 8 by BM25 reached 31.19% against 12.70% for the whole panel; showing names and descriptions first gained 26.72% at 256 tools and 5.17% at 4; names alone lost 6.66% at 4 (tab_count, tab_disclosure_v2).",
  },
  {
    id: "run",
    n: "07",
    title: "Run",
    module: "toolform.sdk.CallLoop",
    what: "The call loop sends the rendered prompt to any OpenAI-compatible endpoint (vLLM, OpenAI) or to the Anthropic Messages API, parses the reply, validates it, runs your executors, and feeds the result back, with a trace of every step and the token cost.",
    sdk: `from toolform.sdk import CallLoop, OpenAICompatClient

client = OpenAICompatClient("http://localhost:8000/v1", model="Qwen/Qwen3-8B", enable_thinking=False)
loop = CallLoop(client, py_tools, guard="standard", max_steps=4)
result = loop.run("What's the forecast for Denver over the next five days?")
print(result.stopped, [c.name for c in result.calls], round(result.cost, 6))`,
    cli: "toolform call tools.py --request \"...\" --base-url http://localhost:8000/v1 --model Qwen/Qwen3-8B --execute",
    http: "The API does not run the loop; ab-test jobs call the endpoint the server is configured with.",
    evidence: "Costs use the paper's two price vectors (tab_cost) unless you pass real prices: a frontier API with the schema priced as a cached prefix, and a self-hosted server.",
  },
];

export default function Framework() {
  useTitle("Framework");
  return (
    <>
      <section className="fw-pagehead">
        <div className="wrap">
          <div className="label">
            <b>FRAMEWORK</b> / HOW IT WORKS
          </div>
          <h1>From a tool file to a checked call</h1>
          <p>
            Seven stages. Each is a module of the Python SDK, a command of the CLI and, except the loop, a route of the HTTP API. Select a stage in the diagram to jump
            to it.
          </p>
        </div>
      </section>
      <div className="wrap" style={{ paddingTop: 40 }}>
        <PipelineDiagram />
        <p className="faint" style={{ fontSize: 13, marginTop: 12 }}>
          The accent marks the path a request takes. The gates run before rendering; the dashed line is the optional measurement on your own endpoint.
        </p>
        <div style={{ marginTop: 32 }}>
          {STAGES.map((s) => (
            <StageSection key={s.id} s={s} />
          ))}
        </div>
        <div className="fw-callout" style={{ marginTop: 16 }}>
          <p>
            <strong>Next:</strong> the <a href={docs("quickstart")}>quick start</a> installs it and runs three commands; the <Link to="/dashboard/advisor">advisor</Link>{" "}
            runs the recommendation in your browser.
          </p>
        </div>
      </div>
    </>
  );
}
