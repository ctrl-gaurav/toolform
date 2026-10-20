"""The call loop against a local OpenAI-compatible server (vLLM, for example).

Start a server first, for example::

    vllm serve Qwen/Qwen3-8B --port 8000

then run::

    python examples/call_loop_vllm.py --model Qwen/Qwen3-8B

The advisor picks the format and protocol for the model, the guard strips
flagged description sentences, and the loop runs the Python tools in
tools/weather.py until the model answers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from toolform.sdk import CallLoop, OpenAICompatClient, Toolset

TOOLS = Path(__file__).resolve().parent / "tools"


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the ToolForm call loop against a local server.")
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--model", default="Qwen/Qwen3-8B")
    ap.add_argument("--request", default="What's the forecast for Denver over the next five days?")
    ap.add_argument("--thinking", action="store_true", help="turn on the Qwen 3 thinking switch")
    args = ap.parse_args()

    client = OpenAICompatClient(args.base_url, model=args.model, enable_thinking=args.thinking)
    if not client.health():
        print(
            f"No OpenAI-compatible server answered at {args.base_url}/models. Start one first, for example:\n"
            f"  vllm serve {args.model} --port 8000",
            file=sys.stderr,
        )
        return 1

    tools = Toolset.from_python(TOOLS / "weather.py")
    loop = CallLoop(client, tools, guard="standard", max_steps=4)
    if loop.recommendation is not None:
        print("advisor:", loop.recommendation.summary())
    result = loop.run(args.request)
    for step in result.steps:
        print(f"\nstep {step.index + 1}: {step.reply.strip()[:400]}")
        for ex in step.executed:
            print(f"  ran {ex['name']}({json.dumps(ex['arguments'])}): {ex.get('result', ex.get('error'))}")
    print(f"\nstopped: {result.stopped}")
    print(f"answer: {result.final_text}")
    print(
        f"tokens: {result.prompt_tokens} prompt, {result.completion_tokens} completion; "
        f"cost {result.cost:.6f} (relative units)"
    )
    return 0 if result.stopped != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
