<p align="center">
  <img src="https://raw.githubusercontent.com/ctrl-gaurav/toolform/main/assets/banner.png" alt="ToolForm: tool interfaces, chosen by measurement" width="100%">
</p>

<p align="center">
  <a href="https://pypi.org/project/toolform/"><img src="https://img.shields.io/pypi/v/toolform.svg?color=4fe3c1&label=pypi" alt="PyPI"></a>
  <a href="https://pypi.org/project/toolform/"><img src="https://img.shields.io/pypi/pyversions/toolform.svg?color=3987e5" alt="Python versions"></a>
  <a href="https://github.com/ctrl-gaurav/toolform/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-22c55e.svg" alt="License: Apache 2.0"></a>
  <a href="https://ctrl-gaurav.github.io/toolform/docs/"><img src="https://img.shields.io/badge/docs-toolform-4fe3c1.svg" alt="Documentation"></a>
</p>

<p align="center">
  <a href="https://ctrl-gaurav.github.io/toolform/"><b>Website</b></a> ·
  <a href="https://ctrl-gaurav.github.io/toolform/docs/"><b>Documentation</b></a> ·
  <a href="https://ctrl-gaurav.github.io/toolform/#/dashboard/advisor"><b>Dashboard</b></a> ·
  <a href="https://pypi.org/project/toolform/"><b>PyPI</b></a> ·
  <b>Paper (coming soon)</b>
</p>

**ToolForm** decides how an agent shows its tools to a language model and reads back the calls.
Give it your tools (OpenAI, Anthropic or MCP JSON, Python functions or TypeScript declarations)
and your model: it recommends a schema format and an answer protocol from a controlled study of
**129 formats, 31 answer protocols and 112 models**, renders the tool block, parses and validates
the reply, guards tool descriptions against hidden instructions, and handles long catalogues.

```python
from toolform import Toolset, recommend, render, parse_reply

tools = Toolset.from_openai("tools.json")
rec = recommend(tools=tools, model="Qwen/Qwen3-8B")
print(rec.summary())   # xml_schema + xml_call, 93.14% expected (65.60 to 93.14 across the table values), checkpoint Qwen/Qwen3-8B

prompt = render(tools, rec.format_id, rec.protocol_id, request="Forecast for Denver, 5 days")
# send prompt.messages to any chat endpoint, then:
parsed = parse_reply(model_reply, tools, rec.protocol_id)
for call in parsed.calls:
    print(call.resolved_name, call.arguments, call.valid)
```

## News

- **2026-10-20** · ToolForm 0.0.1 is on PyPI: `pip install toolform`. The advisor, 129 formats, 31 answer
  protocols, the guard, catalogue tools, a command line, an HTTP API and a web dashboard.
- **2026-10-20** · The [website](https://ctrl-gaurav.github.io/toolform/) and the
  [documentation](https://ctrl-gaurav.github.io/toolform/docs/) are live.
- **Coming soon** · The paper, *ToolForm: A Controlled Study of Tool Formatting for Agents*, on arXiv.

## What the study found

The way a model is shown its tools sets three things: the **schema format** it reads, the **answer
protocol** it writes back in, and the **grading rule** that scores the call. Prior comparisons
changed the first two together; ToolForm's study changed one at a time. Four rules came out:

| Rule | Evidence |
|---|---|
| **Show the parameter schema.** | It raises accuracy by **57.09%** over tool names alone, the largest effect in the study. |
| **Choose the answer protocol before the schema format.** | The protocol changes accuracy **1.22 to 2.00 times** as much as the format. |
| **Prefer a structured format to natural language.** | Natural language is never more accurate on average than the best structured format, at any model size. |
| **Keep the tool list short, and treat tool descriptions as untrusted.** | Going from 1 to 256 tools costs **41.01%**; an instruction hidden in a description is followed on **38.48 to 54.16%** of turns. |

And when you can reach the model, measure: testing eight formats on the target model (400 requests)
reached **69.18%**, against 64.35% for the best fitted rule and 57.97% for the JSON Schema default.

## Install

```bash
pip install toolform                 # SDK and CLI
pip install "toolform[serve]"        # plus the HTTP API behind the dashboard
```

The advisor, the renderers, the parsers and the guard run offline from evidence that ships with the
package. No GPU, no API key.

## What's inside

| | |
|---|---|
| **Advisor** | a format and protocol for your model and tools, with the table behind every number; `measure` runs the eight-format test on your endpoint |
| **Render and parse** | every format and protocol the study measured, the three grading rules as options, and argument validation |
| **Guard** | scans tool descriptions for hidden instructions, invisible characters and other risky text, and cleans them |
| **Catalogue** | names-first disclosure, BM25 or embedding retrieval, token budgets and a planner for long tool lists |
| **Call loop** | runs a model and your Python tools against any OpenAI-compatible or Anthropic endpoint |
| **Interfaces** | Python SDK, the `toolform` CLI, an HTTP API, and a web dashboard |

## Command line

```bash
toolform recommend --tools-file tools.json --model Qwen/Qwen3-8B   # format and protocol, with the evidence
toolform render tools.json --format xml_schema           # the tool block
toolform guard mcp_tools.json                            # scan a third-party manifest
toolform catalogue tools.json --context 32768            # plan a long catalogue
toolform serve                                           # the HTTP API
```

## Documentation

Everything else, from the concepts to every SDK function, CLI option and API route, is in the
**[documentation](https://ctrl-gaurav.github.io/toolform/docs/)**. Runnable examples are in
[`examples/`](https://github.com/ctrl-gaurav/toolform/tree/main/examples).

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](https://github.com/ctrl-gaurav/toolform/blob/main/CONTRIBUTING.md).

## Citation

The paper, *ToolForm: A Controlled Study of Tool Formatting for Agents*, is coming soon. Until then,
please cite the software:

```bibtex
@software{srivastava2026toolform,
  author  = {Srivastava, Gaurav},
  title   = {ToolForm: A Controlled Study of Tool Formatting for Agents},
  year    = {2026},
  url     = {https://github.com/ctrl-gaurav/toolform},
  version = {0.0.1}
}
```

## License

[Apache 2.0](https://github.com/ctrl-gaurav/toolform/blob/main/LICENSE)
