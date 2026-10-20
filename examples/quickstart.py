"""Quick start: load tools, get a recommendation, render the prompt, parse a reply.

These are examples 1 to 3 of the documentation, runnable as they stand:

    python examples/quickstart.py

No model and no network are needed.
"""

from __future__ import annotations

import json
from pathlib import Path

from toolform.advisor import recommend
from toolform.sdk import Toolset, parse_reply, render

TOOLS = Path(__file__).resolve().parent / "tools"


def main() -> None:
    # 1. Load tools from OpenAI JSON, an MCP tools/list result and a Python module.
    openai_tools = Toolset.from_openai(TOOLS / "openai_tools.json")
    mcp_tools = Toolset.from_mcp(TOOLS / "mcp_tools_list.json")
    print("1. load")
    print("  OpenAI:", openai_tools.summary())
    print("  MCP:   ", mcp_tools.names())

    py_tools = Toolset.from_python(TOOLS / "weather.py")  # the functions come along as executors
    print("  Python:", py_tools.names(), "executors:", sorted(py_tools.executors))
    print("  required of get_forecast:", py_tools.to_openai()[0]["function"]["parameters"]["required"])

    # 2. Ask for a format and protocol, and render the prompt.
    rec = recommend(model="Qwen/Qwen3-8B", n_tools=8, tier=3)
    print("\n2. recommend and render")
    print("  ", rec.summary())
    print("  ", rec.explanation)

    prompt = render(py_tools, rec.format_id, rec.protocol_id, request="Forecast for Denver, 5 days")
    print(f"   tool block: about {prompt.tokens_estimate:,} tokens (characters / 4)")
    messages = prompt.messages or []
    print("   messages:", [m["role"] for m in messages])

    # 3. Parse and validate a reply.
    reply = """<function_calls>
  <invoke name="get_forecast">
    <parameter name="city">Denver</parameter>
    <parameter name="days">5</parameter>
  </invoke>
</function_calls>"""
    parsed = parse_reply(reply, py_tools, "xml_call", rule="main")
    call = parsed.calls[0]
    print("\n3. parse")
    print("  ", call.resolved_name, json.dumps(call.arguments), "valid" if call.valid else "invalid")
    print("   format compliant:", parsed.to_dict()["format_compliant"])


if __name__ == "__main__":
    main()
