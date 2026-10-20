"""Guard a third-party MCP manifest and write the cleaned one.

    python examples/guard_mcp.py                       # print the cleaned manifest
    python examples/guard_mcp.py --out cleaned.json    # write it

The manifest in tools/mcp_tools_list.json carries the study's hijack sentence
in one description. The same check runs in CI with
``toolform guard tools/mcp_tools_list.json --fail-on high``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from toolform.guard import guard
from toolform.sdk import Toolset

TOOLS = Path(__file__).resolve().parent / "tools"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("manifest", nargs="?", default=str(TOOLS / "mcp_tools_list.json"))
    ap.add_argument("--out", help="write the cleaned manifest here")
    ap.add_argument("--strictness", default="standard", choices=["lenient", "standard", "strict"])
    args = ap.parse_args()

    tools = Toolset.from_mcp(args.manifest)
    report = guard(tools, strictness=args.strictness, action="strip")
    print(report.summary())
    for f in report.findings:
        print(f"  {f.severity:<6} {f.rule_id} {f.tool}.{f.field}: {f.text!r}")
        print(f"         {f.message}")
    for r in report.removed:
        print(f"  removed from {r['tool']}.{r['field']}: {r['text']!r}")

    cleaned = report.toolset.to_mcp() if report.toolset is not None else tools.to_mcp()
    text = json.dumps(cleaned, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {len(tools)} tools to {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
