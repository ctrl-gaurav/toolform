---
title: Choose a format for your model
order: 40
section: Guides
summary: Ask the advisor for a format and a protocol, read its answer, and know what it rests on.
---

# Choose a format for your model

The advisor picks a schema format and an answer protocol for a model and a situation.
It reads the study's tables, not a model of its own, so every number it prints has a
table behind it. This page shows how to call it, how it computes, and how to read the
result.

If you can call the model, measure instead: [the eight-cell test](measure-your-model.md)
beat every rule in the study, the advisor included.

## Ask

From Python:

```python
from toolform.advisor import recommend
from toolform.sdk import render

rec = recommend(model="Qwen/Qwen3-8B", n_tools=8, tier=3)   # or tools=py_tools to take both from the tools
print(rec.summary())       # xml_schema + xml_call, 90.00% expected (65.30 to 90.00 across the table values), checkpoint Qwen/Qwen3-8B
print(rec.explanation)     # why, with the table behind every number

prompt = render(py_tools, rec.format_id, rec.protocol_id, request="Forecast for Denver, 5 days")
print(prompt.tokens_estimate)       # the tool block, estimated as characters / 4
messages = prompt.messages          # [{"role": "system", ...}, {"role": "user", ...}]
```

Here `py_tools` is a `Toolset`, for example
`Toolset.from_python("examples/tools/weather.py")` from a clone of the repository (see
[Render and parse](render-and-parse.md)). `recommend` takes a `Situation`, or the
situation's fields as keyword arguments:

| field | default | meaning |
|---|---|---|
| `model` | `None` | any model id or name, for example `Qwen/Qwen3-8B` or `claude-opus-5-5` |
| `family` | `None` | a zoo family key, for example `qwen3`, `gemma4`, `gpt-oss`; overrides the match |
| `params_b` | `None` | parameters in billions; parsed from the id when absent |
| `n_tools` | `8` | how many tools the prompt shows |
| `tier` | `3` | the complexity tier, 1 to 5 ([Concepts](../concepts.md)) |
| `token_budget` | `None` | most schema tokens the tool block may take |
| `context_tokens` | `None` | the model's context window; when absent, the zoo's `max_model_len` for a known id |
| `objective` | `"accuracy"` | `"accuracy"` or `"cost"` |
| `price` | `"frontier_api"` | a key of `PRICES`, for the cost objective |
| `rule` | `"main"` | `"main"`, `"symmetric"` or `"as_written"` |
| `protocol` | `None` | fix the answer protocol |
| `candidates` | `None` | format ids to rank; the eight core formats by default |
| `third_party_tools` | `False` | add guard advice |

With `tools=`, the tool count and the tier default to the toolset's (`len(tools)` and
`tools.tier_estimate()`), and the token cost is measured on your tools instead of
scaled from the study's cost table.

From the command line:

```bash
toolform recommend --model Qwen/Qwen3-8B --n-tools 8 --tier 3
toolform recommend --model Qwen/Qwen3-8B --tools-file tools.json --third-party
toolform recommend --family gemma4 --n-tools 32 --rule symmetric --json
```

## How the advisor computes

The algorithm is deterministic. The website's advisor is a port of the same code and is
checked against it on about 380 cases (format, protocol, accuracy, range, catalogue
advice and its reason, tokens and cost), so the browser and the SDK give the same answer.

1. **Resolve the model.** The first match wins: an explicit `family`; an anchor model
   the study ran by name (`claude-opus-5-5` matches "Claude Opus 5.5 (medium)"); a
   checkpoint of the study by its exact id (`Qwen/Qwen3-8B`), which carries its own row
   and its family; an exact id in the model zoo; a list of name patterns (`qwen3`,
   `gemma-4`, `gpt-oss`, `llama`, and so on, written in the evidence as `zoo.json`'s
   `patterns`); otherwise nothing, and the pooled tables are used. `resolve_model`
   shows the match on its own.
2. **Base accuracy.** Under the `main` rule: the checkpoint's own row
   (tab:models_full, three seeds of 50 requests per format), else the anchor's row,
   else the family's row (tab:models_main, the mean of its checkpoints), all at 8 tools
   and tier 3. Under any other rule, or with no match, the pooled main grid (tab:main,
   51 checkpoints, seeds 0 to 2). The model tables exist only under the main rule; the
   advisor warns when it falls back. A family row is not a checkpoint: Qwen3-0.6B
   scores 58.7 with XML and Qwen3-8B 90.0, against the family mean of 77.7, which is why
   a known checkpoint uses its own row.
3. **Tool-count shift.** From the count sweep (tab:count_by_format): the format's
   accuracy at your tool count against 8 tools, interpolated in log2 of the count
   between the measured points 1, 2, 4, ..., 256. More than 256 tools uses the 256-tool
   value and says so.
4. **Tier shift.** From the tier sweep (tab:tier_by_format): the format's accuracy at
   your tier against tier 3. The tier sweep ran at 8 tools, and no table crossed the
   tool count with the tier. So at any other tool count a tier *gain* is not applied (a
   tier loss is), and a warning says so. Without this, an easy tier measured at 8 tools
   lifted a 256-tool estimate above anything measured at 256.
5. **Protocol shift.** From the format by protocol crossing (tab:protocol, pooled over
   35 checkpoints). With the pooled base, the advisor switches from the format's
   default protocol to the best of the five crossing protocols when the gain is at
   least 2.0, the tie threshold of the study's selection rule. With a checkpoint,
   anchor or family row, which was measured with the format's default protocol, it
   keeps that protocol and names the pooled switch in a warning, because a pooled
   switch can go the wrong way for one model (on gpt-oss the XML-leaning fitted rule
   lost 19.56% to always-JSON, tab:selection). A
   fixed `protocol` is used as given; a pairing the study did not measure gets no shift
   and a warning.
6. **Expected accuracy.** The base moved by the three shifts in log-odds:
   `expit(logit(base) + (logit(count at n) - logit(count at 8)) + ...)`. Working in
   log-odds keeps every estimate strictly between 0 and 100, so no value is clipped and
   the ranking is never done on a clipped number. The study measured each factor alone;
   this combination was not itself evaluated.
7. **Range.** The lowest and highest of the table values the point rests on (the
   model's row, the pooled value, the count cell, the tier cell, the crossing cell) and
   of the single-factor estimates. It is never clipped at 0 or 100. It is not a
   confidence interval.
8. **Tokens and cost.** With tools, the rendered tool block's size (characters / 4).
   Without, the study's schema tokens at 8 tools (tab:cost), scaled to your count. The
   output length is the chosen protocol's: tab:cost measured each format with its own
   protocol, so a format paired with another protocol is priced with the output of the
   core formats that answer with it. A protocol no core format uses has no cost.
9. **Budget and context.** With `token_budget`, candidates over the budget are
   dropped; if none are left, the minimal schema comes back as the candidate of last
   resort and the catalogue advice becomes two-stage disclosure. A candidate whose block
   takes more than half the context window (the situation's, else the zoo's
   `max_model_len`) is ranked after those that fit.
10. **Hidden fields.** With tools, a candidate whose tool block does not show a
    required nested field (XML prints `<items type="object"/>` for an array of objects)
    is ranked after those that show every required field, with a warning that names
    the fields.
11. **Rank.** By expected accuracy, or by accuracy per unit cost for the cost
    objective. Candidates within 2.0 of the winner are listed in `tied_with`. A
    repeated candidate counts once.
12. **Catalogue advice.** One-shot, retrieval or two-stage, from the tool count, the
    context window and the budget ([Long catalogues](long-catalogues.md)).
13. **Guard advice.** With `third_party_tools=True`, strip hidden instructions, with the
    injection evidence for the chosen format ([Guard third-party
    tools](guard-third-party-tools.md)).
14. **Explanation and warnings.** Three to eight sentences, every number with its table.

## Read the result

`rec.summary()` is one line. `rec.to_dict()` holds everything; the fields you will read
most are these:

| field | what it says |
|---|---|
| `format_id`, `protocol_id` | the choice |
| `expected_accuracy` | percent, the point value of step 6 |
| `interval` | the range of step 7, not a confidence interval |
| `basis` | `checkpoint:<id>`, `anchor:<name>`, `family:<key>` or `pooled` |
| `context_tokens` | the context window used, the situation's or the zoo's |
| `schema_tokens`, `tokens_source` | the tool block's size, `rendered` from your tools or `study` from tab:cost |
| `cost_per_request` | relative cost under the price vector |
| `tied_with` | candidates within 2.0 of the winner |
| `alternatives` | every other candidate, ranked, with its protocol, accuracy and tokens |
| `catalogue` | the catalogue strategy and its evidence rows |
| `guard` | guard advice when `third_party_tools` is set |
| `warnings` | fallbacks, a tier gain not applied, a kept default protocol, blocks over half the window, hidden fields, the text-protocol caveat |
| `evidence` | every row the number rests on, each with its source table |
| `resolution` | how the model was matched |

A wide range means the tables disagree about this format in this situation. A narrow
range and a large gap to the next alternative is the strongest advice the evidence can
give. Either way, measuring on your model is better.

### The text-protocol warning

When the advisor picks `xml_call` or `nl_intent` under the `main` rule, it adds a
warning: the re-nesting repair that helps these protocols was judged wrong on 12.5%
[8.6, 17.8] of the turns it touched in a human check (results section). If your
deployment cannot re-nest arguments, ask with `rule="as_written"`.

## When to prefer the symmetric rule

Use `rule="main"` when your parser is the protocol's own parser, which is how a
deployment scores calls. Use `rule="symmetric"` when you compare formats or protocols
against each other: it applies the same repair under every protocol, so a format does
not win on its parser. The paper recommends it for measurement. Under `symmetric`, XML
leads JSON Schema by only 1.07% (against 13.80% under `main`), and the advisor uses the
pooled tables, because the family table exists only under `main`.

## The cost objective

With `objective="cost"`, the advisor ranks by expected accuracy per unit of cost. The
cost of a request is the tool block's tokens plus the rest of the prompt as input, and
the study's mean completion tokens as output (tab:cost), priced with one of two
relative price vectors from the paper's cost table:

| name | input per million | cached input per million | output per million | note |
|---|---|---|---|---|
| `frontier_api` | 1.0 | 0.1 | 5.0 | price A; the schema block is priced as a cached prefix |
| `self_hosted` | 0.2 | 0.2 | 2.0 | price B; no cache discount |

These are relative prices, as in the paper. For money, pass real prices through
`Price` to `cost_of` in your own accounting ([Python API reference](../reference/sdk.md)).
The study found accuracy and cost nearly independent across the eight formats, so the
token cost of a format is a separate decision from its accuracy.

## The fitted surface

The study fitted an accuracy surface over model size, tool count and tier. When the
model's size is known and the surface has a fit for the chosen format, the
recommendation's `surface` field shows its prediction with the note "held-out R² 0.219;
shown for extrapolation only". Outside the open checkpoints it was fitted on (0.36 to
122B) the surface is left out, with a warning. The advisor does not use the surface to
choose. In the
selection table, a lookup by count and tier (65.85%) and always XML (65.02%) did as
well as the fitted rule (64.35%), and measuring (69.18%) beat all three
(tab:selection).

```python
from toolform.advisor import Surface

surface = Surface()
print(surface.form, surface.heldout_r2)          # power_decay_in_tools 0.219
print(surface.predict("xml_schema", params_b=8.0, n_tools=16, tier=3))
```
