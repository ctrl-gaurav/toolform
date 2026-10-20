"""Write the website's Python-made test fixture.

`src/framework/__tests__/fixtures/generated_tools_ir.json` holds the generated catalogue (93 tools across
24 domains) as canonical IR. The guard's false-positive test reads it: no benign tool may raise a high
finding at the standard strictness. Run it after the generator changes, with any Python that can import
`toolform`:

    python website/scripts/make_test_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

from toolform.ir import ToolUniverse
from toolform.sdk import generated_toolset

OUT = Path(__file__).resolve().parents[1] / "src" / "framework" / "__tests__" / "fixtures" / "generated_tools_ir.json"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    u = ToolUniverse(tools=list(generated_toolset().tools), universe_id="generated")
    OUT.write_text(json.dumps(u.to_dict(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
