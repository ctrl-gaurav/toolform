---
title: The evidence
order: 63
section: Reference
summary: What the study measured, every evidence file and its source table, the headline facts, how the advisor uses them, and their limits.
---

# The evidence

Every number ToolForm shows comes from the study behind it. This page says what the
study measured, which files carry its results inside the package, where each file came
from, and how the advisor uses it.

## What the study measured

A controlled study of how an agent shows its tools to a model and reads back the calls:

* **129 schema formats**, each a pure rendering of the same canonical tool
  description, so a difference between two formats is presentation, never content.
* **31 answer protocols**, kept as a separate axis from the format.
* **Three grading rules** (`main`, `symmetric`, `as_written`), because one decision in
  the grader, whether a flat argument may be re-nested, changes the ranking.
* **100 open-source and 12 proprietary models.** The advisor's family table has one row
  per open family of the main grid, and one row per anchor model. Anchors are run by
  name and never fitted; for the proprietary ones, a hosted API may re-render the schema
  before the model reads it.
* **24 generated domains with executable tools**, so a call is checked against the
  state of a simulated world, and new uncontaminated tasks can be drawn at will.
* **66 real tool schemas with 1,248 human-written requests**, so the results are not an
  artefact of the generator.
* **Six public benchmarks**, whose tools the study also rendered in its formats.

Every statistical claim of the paper is made on eight core formats (XML, natural
language, Python signature, JSON Schema, YAML, TypeScript, Markdown table and the minimal
schema). The main grid is 8 tools, tier 3, single calls.

## The headline facts

`facts.json` holds the only numbers written by hand. The build checks each one against
the paper's source and fails if the paper does not contain it. `toolform evidence`
prints this list; `GET /api/v1/facts` returns it.

| fact | value | source |
|---|---|---|
| schema formats | 129 | abstract |
| answer protocols | 31 | abstract |
| grading rules | 3 | results section |
| open-source models | 100 | introduction |
| proprietary models | 11 | setup section |
| generated domains with executable tools | 24 | abstract |
| real tool schemas / human-written requests | 66 / 1,248 | abstract |
| public benchmarks | 6 | introduction |
| full schema minus tool names alone | 57.09% [50.40, 64.02] | tab:ladder |
| the schema ladder: names, parameter names, the minimal schema, the full JSON Schema | 2.19%, 25.05%, 38.38%, 59.28% | tab:ladder |
| minimal schema against full JSON Schema | 19.22% [15.58, 23.05] | tab:main |
| XML minus JSON Schema, main rule | 13.80% [9.16, 18.72] | tab:main |
| XML minus JSON Schema, symmetric rule | 1.07% [-2.82, 4.61] | results section |
| XML minus JSON Schema, as written | -3.28% [-6.18, -0.58] | tab:main |
| protocol spread over format spread: main, symmetric, as written | 2.00 [1.40, 3.22], 1.68 [1.07, 3.11], 1.22 [0.86, 1.67] | tab:protocol |
| hallucinated tool names without and with a fixed grammar | 1.07%, 0.01% | results section |
| hidden instruction followed, formats that show a description | 38.48 to 54.16% | tab:pressure |
| decoy tool called | 5.22 to 8.45% | tab:pressure |
| effect of a trust sentence, sentinel and valid payloads | -0.35 [-1.49, 0.70], +0.23 [-0.74, 1.23] | tab:injection_trust |
| followed hijacks that pass schema validation | 58.1% | appendix on presentation under pressure |
| accuracy effect of dropping descriptions | -1.86 to +1.94 (removing them costs 1.86% in the ladder appendix; adding them changes accuracy by -1.94 in tab:components4) | results section |
| the Python signature without its docstring | -12.76 | tab:ladder |
| accuracy at 1 and at 256 tools; the loss | 64.20%, 23.19%; 41.01% | tab:count |
| turns with no answer at 256 tools | 40.77% | tab:count |
| two-stage minus one shot at 256 tools: names; names and descriptions | 18.97 [11.37, 27.15], 26.72 [18.32, 34.98] | tab:disclosure_v2 |
| two-stage minus one shot at 4 tools, names | -6.66 [-9.66, -3.90] | tab:disclosure_v2 |
| two-stage minus one shot at 4 tools, names and descriptions | 5.17 [1.23, 8.58] | tab:disclosure_v2 |
| a 128-tool panel shown whole; top 8 by BM25; top 8 by an embedding | 12.70%, 31.19%, 31.79% | tab:count |
| human check: re-nesting repairs judged wrong | 12.5% [8.6, 17.8] | results section |
| measure eight; fitted rule; always JSON Schema; always XML; lookup by count and tier; oracle | 69.18%, 64.35%, 57.97%, 65.02%, 65.85%, 75.00% | tab:selection |
| requests to measure eight cells | 400 | selection appendix |
| fitted surface, held-out families, R² | 0.219 | results section |
| natural language minus the best structured format | -11.24 [-14.93, -7.59] | results section |
| median spread across the eight formats: anchor models, open checkpoints | 25%, 44% | results section |

Intervals are the paper's 95% intervals. Differences between
formats are in percentage points, written with a `%` as the paper writes them.

## The files

The evidence lives in `toolform/advisor/data/` and ships in the wheel. The website keeps
a byte-identical copy in `website/public/data/framework/`. Every file except the
manifest has the same envelope:

```json
{"schema_version": 1, "name": "families", "source": ["paper:tab_models_main", "paper:tab_models_full"],
 "description": "Strict-call accuracy per family and anchor model on the main grid ...",
 "conditions": {"n_tools": 8, "tier": 3, "regime": "single", "rule": "main", "seeds": "0-2"},
 "data": "..."}
```

A source written `paper:tab_models_main` is the paper's table `tab:models_main`;
`export:...` is the study's results site export; `registry:...` is the live format or
protocol registry; `configs:models` is the model zoo; `framework:...` is produced by the
framework itself for its tests.

| file | source | what it holds | used by |
|---|---|---|---|
| `manifest.json` | the build | the evidence version, each file's sha256, size and sources | `toolform doctor`, the version badge |
| `facts.json` | the paper's prose, checked | the headline facts above | explanations, the CLI footers, the site |
| `formats.json` | `registry:formats`, `export:format_leaderboard` | all 133 registered formats with metadata, and each study format's measured row | candidates outside the core eight, `compare_formats` |
| `protocols.json` | `registry:protocols` | the 31 protocols, with the five crossing protocols marked | protocol names |
| `core_main.json` | tab:main | the eight core formats under the three rules, the paired contrasts against JSON Schema, the real-tool arm | the pooled base accuracy, the evidence range |
| `families.json` | tab:models_main, tab:models_full | accuracy per family and anchor model, and per open-source checkpoint (`checkpoints`), per core format, 8 tools, tier 3, main rule | the checkpoint, anchor and family base accuracy |
| `protocol_crossing.json` | tab:protocol | format by protocol under each rule, 35 checkpoints, and the spread ratios | the protocol shift and the protocol switch |
| `tool_count.json` | tab:count_by_format, tab:count | accuracy and empty turns by tool count per format; the pooled sweep; the retrieval rows | the count shift, the catalogue advice |
| `tiers.json` | tab:tier_by_format | accuracy and empty turns by tier per format; the tier definitions | the tier shift |
| `cost.json` | tab:cost, `export:cost_pareto` | tokens per request and accuracy per token and per price for the core formats at 8 tools; the two price vectors; the cost frontier of every format | token estimates without tools, the cost objective |
| `injection.json` | tab:pressure, tab:injection_trust | hidden-instruction and decoy rates per format; the trust-line experiment | guard advice, the guard's evidence |
| `disclosure.json` | tab:disclosure_v2 | two-stage disclosure against one shot by tool count | the catalogue advice |
| `selection.json` | tab:selection | the selection strategies per held-out family | the measure hint, the evidence explorer |
| `ladder.json` | tab:ladder, tab:names_only | the schema ladder and the names-only table | the evidence explorer |
| `zoo.json` | the model zoo | every model with its family, size, kind, context window; the family patterns | model resolution |
| `surface.json` | the law fits (results repository) | the fitted surface per format and its held-out R² | `Surface.predict` |
| `sample_renders.json` | the framework | the sample tool rendered in all 133 registered formats | the playground offline |
| `render_cases.json` | the framework | six toolsets rendered in the eight core formats | parity tests of the browser renderers |
| `advisor_cases.json` | the framework | about 380 situations and the Python advisor's answers, with the catalogue reason and the cost | parity tests of the browser advisor |
| `guard_cases.json` | the framework | about 55 texts and the Python guard's findings | parity tests of the browser guard |

Formats outside the core eight rest on the site export, not on the paper's tables.
Every surface that shows such a number says so, and the advisor adds a warning when you
include one as a candidate.

## How the advisor uses the evidence

For one situation, the advisor reads (the steps are in [Choose a format for your
model](guides/choose-a-format.md)):

1. `zoo.json`, the anchor rows and the checkpoint rows of `families.json` to match the
   model;
2. `families.json` (main rule, a match: the checkpoint's row, the anchor's or the
   family's) or `core_main.json` (otherwise) for the base accuracy of each candidate at
   8 tools and tier 3;
3. `tool_count.json` and `tiers.json` for the shifts to your tool count and tier;
4. `protocol_crossing.json` for the protocol shift, and whether to switch protocol;
5. `cost.json` for tokens and cost when no tools are given;
6. `disclosure.json` and `tool_count.json` for the catalogue advice;
7. `injection.json` for the guard advice;
8. `facts.json` for the explanation, the warnings and the measure hint;
9. `surface.json` for the extrapolation shown beside the answer.

The combination moves the model's base value by the count, tier and protocol shifts
measured on pooled checkpoints, in log-odds, so no estimate passes 0 or 100. A tier gain
(measured at 8 tools) is not applied at other tool counts. The study measured each
factor alone and this combination was not itself evaluated, so the advisor prints the
range across the table values it rests on beside its point value, and always suggests
measuring.

## Limits

These are the limits the paper states, and they carry over to the advisor:

* **The generated tasks isolate a mechanism.** They do not look like production use.
  The real-tool arm (66 schemas, 1,248 requests) checks the main results on real
  schemas.
* **The real-tool schemas come from one framework.**
* **The fitted surface reaches R² = 0.219 on held-out families.** It is shown for
  extrapolation only, never used to choose.
* **The family table exists only under the main rule.** Under the other rules the
  advisor uses pooled numbers and says so.
* **Past 256 tools, and outside tiers 1 to 5, nothing was measured.** The advisor uses
  the nearest measured value and warns.
* **No table crossed two factors.** The tool count, the tier and the protocol were each
  measured alone, so the advisor's combination of them is an estimate the study did not
  test.
* **Anchor models answered through their vendors' APIs or a shared endpoint**, on one
  to three seeds of 25 requests per format, and enter no fit.
* **The guard was not measured by the study.** The study measured how often models
  follow hidden instructions, not how well any detector finds them. The framework's own
  check, on 50 held-out descriptions, is in [Guard third-party
  tools](guides/guard-third-party-tools.md).

The paper's extended appendix lists every limitation in full.

## How the evidence is built

The evidence files are built from the study's tables when the paper's tables change, and
ship inside the package (`toolform/advisor/data/`). The build checks every fact against the
paper's text and fails on a table row it does not know, so a renamed row is caught.
`manifest.json` records each file's sha256 and an `evidence_version` (the build date and a
counter); `toolform doctor` checks the hashes. The build itself is part of the study's code,
which will be released with the study's records.
