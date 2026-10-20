/* Code samples: the landing page's tabs and the advisor's "Copy Python" and
 * "Copy CLI" strings. They use the exact names of the SDK and CLI in the
 * design document, section (b) and (e). */

import { situationArgs, type Situation } from "./advisor";

export const INSTALL = "pip install toolform";

export const PY_EXAMPLE = `from toolform.advisor import recommend
from toolform.sdk import Toolset, render, parse_reply

tools = Toolset.from_openai("tools.json")
rec = recommend(model="Qwen/Qwen3-8B", tools=tools)
print(rec.summary())      # the format, the protocol, the expected accuracy and its range
print(rec.explanation)    # why, with the table behind every number

prompt = render(tools, rec.format_id, rec.protocol_id, request="Forecast for Denver, 5 days")
reply = my_model(prompt.messages)                      # any chat model you call
parsed = parse_reply(reply, tools, rec.protocol_id, rule="main")
for call in parsed.calls:
    print(call.resolved_name, call.arguments, call.valid)`;

export const CLI_EXAMPLE = `# the format and protocol for a model, with the evidence behind them
toolform recommend --model Qwen/Qwen3-8B --n-tools 8 --tier 3

# fail a CI job when a third-party MCP manifest hides instructions
toolform guard mcp_tools.json --strictness standard --fail-on high

# measure eight formats on your own endpoint: 8 x 50 = 400 requests
toolform ab-test --base-url http://localhost:8000/v1 --model Qwen/Qwen3-8B`;

export const HTTP_EXAMPLE = `toolform serve                     # http://127.0.0.1:8765, docs at /docs

curl -s http://127.0.0.1:8765/api/v1/recommend \\
  -H 'content-type: application/json' \\
  -d '{"situation": {"model": "Qwen/Qwen3-8B", "n_tools": 8, "tier": 3}}'`;

export function pythonFor(s: Situation): string {
  const args = situationArgs(s).map(([k, py]) => `${k}=${py}`);
  const call = args.length > 3 ? `recommend(\n    ${args.join(",\n    ")},\n)` : `recommend(${args.join(", ")})`;
  return `from toolform.advisor import recommend\n\nrec = ${call}\nprint(rec.summary())\nprint(rec.explanation)`;
}

export function cliFor(s: Situation): string {
  return `toolform recommend ${situationArgs(s).map(([, , cli]) => cli).join(" ")}`;
}
