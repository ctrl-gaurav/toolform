---
title: FAQ
order: 80
section: Project
summary: Short answers to the questions people ask first, each with the number behind it.
---

# FAQ

## Is JSON Schema wrong?

No. It depends on the model, the grading rule and the protocol. On the study's main
grid, XML leads JSON Schema by 13.80% under the main rule, by 1.07% under the
symmetric one, and trails it by 3.28% when replies are graded as written (tab:main).
For some models JSON Schema is the best choice: it was the most accurate format for
several of the anchor models (tab:models_main), and always using it was the best
strategy for the gpt-oss family (tab:selection). What is wrong is
choosing it by habit. Averaged over held-out families, always using JSON Schema reached
57.97%, against 69.18% for measuring eight formats on the target model.

## Why does the advisor so often pick XML?

Because under the main rule it was the most accurate core format on the main grid
(67.52%, against 53.71% for JSON Schema, tab:main), and the best format for most of the
open families (tab:models_main). Two cautions. Much of XML's lead under the main rule
comes from its protocol's parser, which re-nests flat arguments; under the symmetric
rule, which applies that repair everywhere, the lead shrinks to 1.07%. And a human check
judged the repair wrong on 12.5% of the turns it touched. The advisor prints that
warning whenever it picks a text protocol under the main rule.

## Why not always natural language?

Natural language minus the best structured format is -11.24% [-14.93, -7.59] (results
section). It is also the weakest format for most of the anchor models (results
section). Models read structure better than prose when the call has
structure.

## Does a grammar or constrained decoding fix it?

It fixes one thing. With a fixed grammar, hallucinated tool names fall from 1.07% to
0.01%, but the gap between formats stays (results section). A grammar makes the reply
well formed; it does not make the model understand the tool.

## Which matters more, the format or the protocol?

The protocol. Over 35 checkpoints, the answer protocol changed accuracy 1.22 to 2.00
times as much as the schema format, depending on the grading rule (tab:protocol).
Choose the protocol first. `recommend` switches away from a format's default protocol
when the crossing table shows a gain of at least 2.0.

## Does it work with MCP?

Yes. `Toolset.from_mcp` reads a `tools/list` result, the full JSON-RPC response, or a
bare list of tools, and keeps MCP annotations. `to_mcp` writes them back. `toolform
guard manifest.json --from mcp --fail-on high` scans an MCP server's tools before you
connect an agent to it. ToolForm does not run an MCP client or server; it works on the
tool definitions.

## Does the guard make third-party tools safe?

No. It removes the plain attack the study measured, a sentence hidden in a description,
which models followed on 38.48 to 54.16% of turns in every format that shows a
description (tab:pressure). It is a rule-based detector. On a held-out set of 50
descriptions it flagged 12 of 25 injected ones and 1 of 25 benign ones at high
severity, so it missed half, and an attacker who writes around its rules can get past
it. It does not scan
tool results. Use it as one gate among several, and check the values that matter in
your executors. See [Guard third-party tools](guides/guard-third-party-tools.md).

## Does telling the model that tool metadata is untrusted help?

Not measurably. A sentence in the system prompt calling tool metadata untrusted
changed the rate at which models followed a hidden instruction by -0.35 and +0.23, and
both intervals include zero (tab:injection_trust).

## How many tools can I show at once?

Fewer than you think. Accuracy fell from 64.20% at 1 tool to 23.19% at 256, and at 256
tools 40.77% of turns returned nothing (tab:count). From 32 tools the advisor suggests
retrieval, and from 64 tools two-stage disclosure, which gained 26.72% at 256 tools with
names and descriptions first (tab:disclosure_v2). See [Long
catalogues](guides/long-catalogues.md).

## Do I need a GPU?

No. The advisor, the renderers, the parsers, the guard, the catalogue planner, the CLI,
the API and the dashboard run on a CPU, from evidence that ships with the package. You
need a model only to run the call loop or to measure your own model, and that model can
be anywhere you can reach over HTTP.

## Do I need the openai or anthropic packages?

No. The clients use the standard library's HTTP. The core install needs numpy, PyYAML,
typer, rich and tqdm; the `serve` extra adds FastAPI, uvicorn and pydantic.

## How is this different from a prompt library?

A prompt library gives you templates. ToolForm gives you the templates the study
measured, the numbers it measured for them, and the procedure to measure them on your
own model. Every renderer and parser is the one the study used, so a prompt rendered by
ToolForm is the prompt behind the numbers. And it keeps format and protocol, the two
halves most libraries fix together, as separate choices.

## Should I trust the advisor or measure?

Measure if you can. Measuring eight formats on the target model reached 69.18%, against
64.35% for the fitted rule, 65.02% for always XML and 65.85% for a lookup by tool count
and tier (tab:selection). It costs 400 requests. The advisor is for when you cannot
call the model yet, or need a default today. See [Measure your own
model](guides/measure-your-model.md).

## My model is not in the study. What does the advisor do?

It tries, in order, an anchor name, a checkpoint of the study by its exact id (which
has its own row), an exact id in the model zoo and a list of family patterns (so
`my-org/Qwen3-14B-finetune` still matches Qwen 3 and gets the family's mean). If nothing
matches, it uses the tables pooled over the study's 51 main-grid checkpoints and says
`basis: pooled`. In every case, measuring on your model is the better answer: a family
mean can be far from one checkpoint (Qwen3-0.6B scores 58.7 with XML, Qwen3-8B 90.0, the
Qwen 3 mean 77.7).

## What is the range printed beside the expected accuracy?

The lowest and highest of the numbers the point rests on: the model's row, the pooled
value, the count curve, the tier curve and the crossing cell, and the estimates that
move the base by one factor at a time. It is not a confidence interval, and it is never
clipped at 0 or 100. A wide range means the tables disagree. The point itself combines
per-factor tables in log-odds; the study never tested that combination.

## Can I add my own format or protocol?

Yes, in the registries (`toolform.formats`, `toolform.protocols`). A new
format renders and parses at once; it has no study numbers until someone measures it,
and the advisor ranks it only if you add it to `candidates`, where it gets no evidence
and a warning. See [Contributing](contributing.md).

## How do I install it?

`pip install toolform`, or `pip install "toolform[serve]"` for the HTTP API. See the
[Quick start](quickstart.md).

## How do I cite it?

The paper is coming soon. Until then, cite the software; [Citing ToolForm](citing.md)
has the BibTeX.
