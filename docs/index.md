---
title: ToolForm
order: 10
section: Start
summary: What ToolForm is, what it does, and how it relates to the study behind it.
---

# ToolForm

**Tool interfaces, chosen by measurement.**

ToolForm is an open-source framework that decides how an agent shows its tools to a
model and reads back the calls. Give it your tools (OpenAI or MCP JSON Schema, a Python
module or a TypeScript file) and your model, and it recommends a schema format and an
answer protocol by combining the per-factor tables of a controlled study of 129
formats, 31 answer protocols and 112 models: the model's own row, and the measured
effect of the tool count, the tool complexity and the protocol. The study measured each
factor alone; this combination was not itself evaluated, and the advisor says so beside
every number. If you can reach the model, it measures eight
formats on your own endpoint in 400 requests, the procedure that beat every fixed rule
in the study (69.18% against 64.35% for the fitted rule and 57.97% for the JSON Schema
default). It renders the tool block in any of the 129 formats, parses replies under any
of the 31 protocols with the study's three grading rules as explicit options, validates
arguments against the schema, flags instructions hidden in third-party tool
descriptions (which models followed on 38.48 to 54.16% of turns in every format that
shows a description), and handles long catalogues with names-first disclosure and
retrieval. It ships as a Python SDK, a command line tool, an HTTP API and a web
dashboard that works offline from the study's evidence.

## The problem

Every agent system has to show its tools to the model somehow: JSON Schema, XML,
YAML, TypeScript signatures, Python signatures, a Markdown table or plain prose. It also has
to tell the model how to write the call back: a JSON object, XML, a Python call, a
sentence. Most systems make both choices once, by habit, and never measure them.

The study behind ToolForm measured them. The right choice depends on the model, the
grading rule, the number of tools and how complex they are:

* The parameter schema is worth 57.09% over tool names alone (tab:ladder).
* XML leads JSON Schema by 13.80% under the main rule, by 1.07% under the symmetric
  one, and trails it by 3.28% when replies are graded exactly as written (tab:main and
  the results section).
* The answer protocol changes accuracy 1.22 to 2.00 times as much as the schema format,
  depending on the grading rule (tab:protocol).
* A fixed grammar leaves the format gap in place, while hallucinated tool names fall
  from 1.07% to 0.01% (results section).
* An instruction hidden in a tool description is followed on 38.48 to 54.16% of turns
  in every format that shows a description (tab:pressure).
* Going from 1 to 256 tools costs 41.01% (tab:count).
* Measuring eight cells on the target model (69.18%) beats every fixed rule (64.35%
  for the fitted rule) and the JSON Schema default (57.97%) (tab:selection).

ToolForm turns those measurements into defaults you can defend, and gives you the
procedure to check them on your own model.

## What it does

The framework runs in seven stages. Each is one SDK call and one CLI command, and each
but the call loop is also one HTTP route.

1. **Load.** Read tools once into the canonical IR (`toolform.ir.ToolIR`), from
   OpenAI function JSON, Anthropic tool JSON, an MCP `tools/list` result, a Python
   module, a TypeScript declaration file or the IR itself. Export back to any of the
   JSON shapes. (`toolform.sdk.Toolset`, `toolform convert`)
2. **Recommend.** Pick a (format, protocol) pair for a model and a situation, with the
   expected accuracy, the range across the table values it rests on, the token cost, the evidence
   rows it rests on and a plain-English reason. Or measure eight formats on your own
   endpoint and pick the best. (`toolform.advisor.recommend`, `ab_test`;
   `toolform recommend`, `toolform ab-test`)
3. **Render.** Write the tool block in any registered format and the answer instruction
   of any protocol, assembled into chat messages exactly as the study assembled them.
   (`toolform.sdk.render`, `toolform render`)
4. **Parse.** Read a reply with the protocol's strict parser, under one of the three
   grading rules, and validate each call's arguments against the schema.
   (`toolform.sdk.parse_reply`, `toolform parse`)
5. **Guard.** Flag or strip instructions hidden in third-party tool metadata, and
   report what was removed. (`toolform.guard.guard`, `toolform guard`)
6. **Catalogue.** For long tool lists, plan one-shot, retrieval or names-first
   two-stage disclosure from the study's measurements, and run them.
   (`toolform.catalogue.plan_catalogue`, `toolform catalogue`)
7. **Run.** Drive a call loop against any OpenAI-compatible endpoint (vLLM, OpenAI) or
   the Anthropic Messages API, with executors, tracing and cost accounting.
   (`toolform.sdk.CallLoop`, `toolform call`)

## The study in numbers

| | |
|---|---|
| schema formats | 129 |
| answer protocols | 31 |
| grading rules | 3 |
| open-source models | 100 |
| proprietary models | 12 |
| anchor models, used in no fit | 20 (12 proprietary, 8 open-source) |
| generated domains with executable tools | 24 |
| real tool schemas | 66, with 1,248 human-written requests |
| public benchmarks | 6 |
| graded turns checked by hand | 600 |
| graded cells | 571,687 |
| graded requests | 32.1M |

Every number the framework shows comes from the study's tables. The advisor ships those
tables as JSON inside the package, so it works offline and needs no GPU.
[The evidence](evidence.md) lists every file and the table it came from.

## Who it is for

* An engineer wiring tools into an agent who wants a defensible default and a way to
  check it on their own model.
* A platform team that accepts third-party tools (MCP servers, plugins) and needs a
  gate on the description channel.
* A researcher who wants the study's renderers, parsers and graders as a library.

## Where to go next

* [Quick start](quickstart.md): install, three commands, five lines of Python.
* [Concepts](concepts.md): format, protocol, grading rule, the evidence, the guard and
  the catalogue.
* [Choose a format for your model](guides/choose-a-format.md): how the advisor decides.
* [Measure your own model](guides/measure-your-model.md): the eight-cell test.
* [Guard third-party tools](guides/guard-third-party-tools.md): the description
  channel and what to do about it.
* [CLI reference](reference/cli.md), [Python API reference](reference/sdk.md) and
  [HTTP API reference](reference/http-api.md).

## How it relates to the study

ToolForm is built on the renderers, parsers and graders of a controlled study of tool formatting
(the paper is coming soon): every renderer and every parser in the package is the one the study
used, so a prompt rendered by ToolForm is the prompt the study measured. The study's tables ship
with the package as the evidence the advisor reads. The rest of the study's code (its run harness,
law fitting and experiment definitions) and its records will be released separately.

## Honesty rules

* The advisor always names the table a number came from, and says when it falls back
  from model evidence to pooled evidence, when a situation is outside the measured
  range (more than 256 tools, a tier outside 1 to 5), and that its combination of the
  per-factor tables was not itself evaluated.
* The advisor's interval is the range across the table values it rests on. It is not a
  confidence interval.
* The guard is a heuristic detector. The study measured how often models follow a
  hidden instruction, not this detector. We measured it once on a held-out set of 50
  descriptions: it flagged 12 of 25 injected ones and 1 of 25 benign ones at high
  severity ([Guard third-party tools](guides/guard-third-party-tools.md)).
* The fitted surface is shown only as an extrapolation aid, with its held-out R² of
  0.219 beside it.

ToolForm is released under the Apache License 2.0.
