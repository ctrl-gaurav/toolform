---
title: Long catalogues
order: 44
section: Guides
summary: What happens to accuracy as the tool list grows, and how to plan one-shot, retrieval or two-stage disclosure.
---

# Long catalogues

The more tools a prompt shows, the worse the model calls them. This guide shows how
much, and how the catalogue module (`toolform.catalogue`) keeps a long list usable.

## What the study measured

Accuracy by tool count, pooled over the eight core formats at tier 3 (tab:count):

* **64.20% at 1 tool, 23.19% at 256 tools**: going from 1 to 256 tools costs 41.01%.
* **Empty turns.** At 256 tools, 40.77% of turns returned nothing at all. Past 64 tools,
  part of the loss is a prompt that no longer fits, not a wrong call.
* **Retrieval.** On a 128-tool panel, showing the whole panel reached 12.70%. Showing
  only the top 8 tools by BM25 reached 31.19%, and by an embedding 31.79%. The gold
  tool was not forced into the top 8, so a retrieval miss made the request
  unanswerable, and the numbers include those misses.
* **Two-stage disclosure (novel).** Show the names first, let the model pick one, then
  show that tool's full schema. At 256 tools, names first gained 18.97% [11.37, 27.15]
  over the one-shot JSON Schema block, and names with one-line descriptions gained
  26.72% [18.32, 34.98]. At 4 tools, names only lost 6.66% [-9.66, -3.90]: with a short
  list, the extra step costs more than it saves (tab:disclosure_v2).

## The three strategies

The advisor and `plan_catalogue` use the same thresholds from the same evidence:

| strategy | when | why |
|---|---|---|
| `two_stage` | 64 tools or more, or a tool block over half the context window | names and descriptions first gained 11.24% at 64 tools and 26.72% at 256 (tab:disclosure_v2) |
| `retrieve` | 32 to 63 tools | top 8 by BM25 reached 31.19% against 12.70% for a 128-tool panel shown whole (tab:count); it needs the request text, so it runs per request |
| `one_shot` | fewer than 32 tools, and the block fits | at small counts the evidence is mixed: names alone lost 6.66% at 4 tools, names and descriptions first gained 5.17% at 4 and changed accuracy by +1.88% at 16, an interval that includes zero, for a second model call per request |

A block over the token budget makes the plan `two_stage` (the reason names the budget),
unless a query lets retrieval bring it under. An empty catalogue is refused.

## Plan

```python
from toolform.catalogue import plan_catalogue
from toolform.sdk import generated_toolset

tools = generated_toolset()                # 93 generated tools across 24 domains
plan = plan_catalogue(tools, format_id="xml_schema")
print(plan.strategy, plan.n_tools, plan.schema_tokens)    # two_stage 93 20062
print(plan.reason)
for row in plan.evidence:
    print(row.source, row.label, row.value)
```

`plan_catalogue(toolset, *, format_id="xml_schema", context_tokens=None,
budget_tokens=None, query=None, k=8)` returns a `CataloguePlan`. With a `query` and the
`retrieve` strategy, `plan.retrieval` holds the ranking; with a `query` and the
`two_stage` strategy, `plan.selection_messages` holds the first-stage prompt.

From the command line:

```bash
toolform catalogue tools.json --format xml_schema --context 32768
toolform catalogue tools.json --query "What is the weather in Paris tomorrow?" --k 8
```

## Retrieve

```python
from toolform.catalogue import retrieve

hits = retrieve(tools, "What is the weather in Paris tomorrow?", k=8, keep=["bash"])
print(hits.ranked[:3])        # [(name, score), ...], best first
prompt_tools = hits.toolset   # the top k, in ranked order
```

`method="bm25"` (the default) uses the study's own BM25 scorer over each tool's name,
description and parameters. `method="embed"` uses an embedding model and needs the
`sentence-transformers` package; without it, `retrieve` raises `ImportError` naming the
package. `keep` names tools that are always included; they take slots from the top k.

Retrieval runs per request. Render `hits.toolset` with the format of your choice for
each request, and keep the order stable across requests that share a prefix if your
server caches prefixes.

## Two-stage disclosure

```python
from toolform.catalogue import TwoStage
from toolform.sdk import OpenAICompatClient

client = OpenAICompatClient("http://localhost:8000/v1", model="Qwen/Qwen3-8B", enable_thinking=False)
two = TwoStage(tools, include_descriptions=True, format_id="json_schema_openai", protocol_id="json_object")
result = two.run(client, "What is the weather in Paris tomorrow?")
print(result.selected, result.selection_failed)
print(result.parsed.calls if result.parsed else None)
print(result.prompt_tokens, result.completion_tokens)     # both stages
```

This is exactly the study's second two-stage design:

1. **Selection.** The catalogue is rendered with `names_desc_then_schema` (names and
   one-line descriptions) when `include_descriptions` is true, else
   `names_then_schema_v2` (names only), through the study's prompt builder, and
   `SELECTION_ASK` is appended to the request: "First step: reply with the exact name
   of the one tool you would use for this request, and nothing else. You will be shown
   that tool's full definition next." The selection call uses `max_tokens=48`.
2. **Reading the selection.** Every catalogue name contained in the reply
   (case-insensitive), the longest winning; otherwise the first word, stripped of quotes
   and punctuation, if it is a name. A reply that names no tool is a selection failure:
   the second stage does not run, and there is no fallback to the first tool.
3. **The call.** The selected tool alone is rendered with `format_id` and
   `protocol_id`, and the reply is parsed with `parse_reply` against the whole
   catalogue, so a near twin of the right tool still resolves.

You can drive the stages yourself with `selection_messages(request)`,
`parse_selection(reply)` and `call_messages(request, selected)`.

The cost is a second model call per request. At 16 tools the two-stage gain was small
and its interval included zero (tab:disclosure_v2), so the plan keeps one-shot there.

## Fit a token budget

```python
from toolform.catalogue import fit_to_budget

fit = fit_to_budget(tools, "xml_schema", 4000, query="What is the weather in Paris tomorrow?")
print(fit.fits, fit.tokens_before, fit.tokens_after)
print(fit.steps)       # what was done, in order
print(fit.dropped)     # [{"tool", "reason", "tokens"}]
reduced = fit.toolset
```

`fit_to_budget` stops as soon as the rendered block fits (tokens estimated as
characters / 4):

1. render as is;
2. with a `query`, rank the tools by retrieval and drop the lowest-ranked first;
3. without a query, drop the longest descriptions of optional parameters first
   (descriptions of required parameters stay);
4. drop tools from the end of the list, never those named in `keep`.

Step 3 changes what the model reads. The study's description ablation found dropping
descriptions cost little (1.86% over all cells, the ladder appendix), except for the
Python signature, which lost 12.76. `fits` is false when nothing is left to drop.

From the command line: `toolform catalogue tools.json --budget 4000 --fit --out
reduced.json`.
