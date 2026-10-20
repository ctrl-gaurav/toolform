"""Measure eight formats on your own model and pick the best.

    python examples/measure_your_model.py --base-url http://localhost:8000/v1 --model Qwen/Qwen3-8B

With --examples and --tools, the requests are your own labelled ones
(tools/examples.jsonl over tools/openai_tools.json is a small sample);
without them, generated requests with executable tools and gold calls. In
the study, measuring eight formats this way reached 69.18%, against 64.35%
for the fitted rule and 57.97% for the JSON Schema default.
"""

from __future__ import annotations

import argparse
import json
import sys

from toolform.advisor import ab_test, load_examples
from toolform.sdk import OpenAICompatClient, Toolset


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure eight formats on an OpenAI-compatible endpoint.")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--n-requests", type=int, default=50, help="generated requests per format")
    ap.add_argument("--tools", help="your tools (OpenAI JSON), with --examples")
    ap.add_argument("--examples", help="labelled requests, one JSON object per line")
    ap.add_argument("--rule", default="symmetric", choices=["main", "symmetric", "as_written"])
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", help="write the report JSON here")
    args = ap.parse_args()

    client = OpenAICompatClient(args.base_url, model=args.model)
    if not client.health():
        print(f"No OpenAI-compatible server answered at {args.base_url}/models.", file=sys.stderr)
        return 1
    toolset = Toolset.from_openai(args.tools) if args.tools else None
    examples = load_examples(args.examples) if args.examples else None

    def progress(done: int, total: int) -> None:
        if done == total or done % 25 == 0:
            print(f"  {done}/{total} requests", file=sys.stderr)

    report = ab_test(
        client,
        n_requests=args.n_requests,
        rule=args.rule,
        toolset=toolset,
        examples=examples,
        concurrency=args.concurrency,
        keep_records=bool(args.out),
        progress=progress,
    )
    print(report.summary())
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report.to_dict(), fh, indent=2)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
