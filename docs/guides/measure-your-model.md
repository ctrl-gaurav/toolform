---
title: Measure your own model
order: 46
section: Guides
summary: Run the eight core formats on your own endpoint, 400 requests, and keep the best. It beat every rule in the study.
---

# Measure your own model

Every rule, the advisor's included, is a guess about a model from the models the study
ran. If you can call the model, you do not have to guess. Run the eight core formats on
it, each with its default protocol, and keep the best. This is the "measure eight"
procedure of the paper's selection appendix, and it beat every rule the study tried.

## Why measure

The paper scored five ways of choosing a format on the same held-out conditions: 602
conditions over 16 model families, each family held out in turn, scored on measured
accuracy (tab:selection, 55,732 cells).

| strategy | mean accuracy |
|---|---|
| always JSON Schema, the usual default | 57.97% |
| the fitted selection rule | 64.35% |
| always XML | 65.02% |
| best format per (tool count, tier), a lookup table | 65.85% |
| **measure eight formats once on the target model** | **69.18%** |
| the oracle: best format per condition in hindsight | 75.00% |

Measuring eight formats once on the target model and using the best of them everywhere
else closed more than half of the gap between the JSON Schema default and the oracle.
The oracle is an upper bound inflated by seed noise, not a reachable target. Measuring
helped most, against the fitted rule and always XML, on the families where the common
choice fails: gpt-oss, the DeepSeek-R1 distils, the Llama tool-RL checkpoints, xLAM and
SmolLM (tab:selection).

The cost is 400 requests: 8 formats times 50 requests.

## Run it

```python
from toolform.advisor import ab_test

report = ab_test(client, n_requests=50)     # 8 formats x 50 generated requests = 400 calls
print(report.summary())                     # winner, accuracy per format, Wilson intervals
```

`client` is any `ChatClient`: `OpenAICompatClient` for vLLM or a hosted endpoint,
`AnthropicClient`, or `StubClient` in a test. For example:

```python
from toolform.sdk import OpenAICompatClient

client = OpenAICompatClient("http://localhost:8000/v1", model="Qwen/Qwen3-8B", enable_thinking=False)
```

The signature:

```python
ab_test(client, *, formats=CORE_FORMATS, protocols=None, n_requests=50, n_tools=8, tier=3,
        seed=0, rule="symmetric", toolset=None, examples=None, max_tokens=512,
        temperature=0.0, concurrency=4, keep_records=False, progress=None) -> MeasureReport
```

* `formats`: the formats to measure; the eight core formats by default.
* `protocols`: a mapping from format to protocol, to pair a format with something other
  than its default protocol.
* `n_requests`: requests per format.
* `n_tools`, `tier`, `seed`: the generated task set (below).
* `rule`: the grading rule; `symmetric` by default, because it treats every protocol the
  same and the paper recommends it for measurement. Use `main` to score the way a
  deployment with each protocol's own parser would.
* `concurrency`: requests in flight at once.
* `keep_records`: keep every request, reply and grade in `report.records`.
* `progress(done, total)`: called after each request.

## Generated tasks or your own

**Generated tasks (the default).** The requests come from the study's generator:
`toolform.generator.generate_instances(n_requests, n_tools=n_tools, tier=tier,
regime="single", seed=seed)`. Each is a tool set with executable semantics and a gold
call. Every format sees the same instances, so the comparison is paired: a difference
between two formats is the format, not the draw. Set `n_tools` and `tier` to your
situation (use `toolset.tier_estimate()` for the tier of your own tools).

**Your own examples.** Pass labelled requests and your toolset:

```python
from toolform.advisor import ab_test, load_examples
from toolform.sdk import Toolset

tools = Toolset.from_openai("tools.json")
examples = load_examples("examples.jsonl")
report = ab_test(client, toolset=tools, examples=examples, rule="symmetric")
```

`examples.jsonl` holds one example per line: the request and its gold calls. An empty
`calls` list means the right answer is no call at all.

```json
{"request": "What's the forecast for Denver for the next five days?", "calls": [{"name": "get_forecast", "arguments": {"city": "Denver", "days": 5}}]}
{"request": "Tell me a joke.", "calls": []}
```

Your own examples measure your tools and your traffic, which the generated tasks do
not. They also need care: every value in a gold call must be stated in the request, or
the task is unanswerable and the accuracy means nothing. The study's generator
enforces that; for your own file, you have to.

## How each reply is graded

Each prompt is built by the study's prompt builder for that format and protocol. Each
reply is parsed strictly and leniently and graded with the study's grader
(`toolform.eval.grader.grade_turn`); the correct column is the rule's
(`call_exact`, `call_exact_symmetric` or `call_exact_as_written`). A client error counts
as a wrong answer and in `errors`; a reply cut off at `max_tokens` counts as a wrong
answer and in `truncated`. Thinking models need thinking off, or a budget large enough
for it: the study turned thinking off for Qwen 3 and Qwen 3.5, and the CLI and the HTTP
API do so by default for those families.

Before the first request, `ab_test` asks a client that has a `health()` method (as
`OpenAICompatClient` does, `GET /models`) whether the endpoint answers, and raises
`ClientError` at once if not. When every request fails, it raises `ClientError` with the
first error instead of naming a winner.

## Read the report

`MeasureReport.scores` holds one `FormatScore` per format, best first:

| field | meaning |
|---|---|
| `accuracy` | percent correct under the rule |
| `interval` | the Wilson 95% interval, in percent |
| `parse_strict` | percent of replies the protocol's own parser read |
| `hallucinated` | percent of replies naming a tool that was not offered |
| `schema_valid` | percent of replies whose call passed validation |
| `prompt_tokens_mean`, `completion_tokens_mean` | mean tokens per request |
| `errors` | client errors |
| `truncated` | replies cut off at `max_tokens` |

`verdict` says what the data can support:

| verdict | when | `winner` |
|---|---|---|
| `winner` | the leader's Wilson interval is clear of at least one other format's | the best format |
| `no_difference` | every format scored zero, or every interval overlaps the leader's | `None` |
| `inconclusive` | more than a quarter of the requests failed | `None` |

`verdict_reason` says why in a sentence. `tied_with` lists formats whose Wilson interval
overlaps the leader's (`scores[0]`). With 50 requests per format, the
intervals are wide: at 70% correct, the 95% Wilson interval runs from about 56% to 81% (a
property of the interval, not a study number). When several formats tie, choose among
them on token cost (`prompt_tokens_mean`), or raise `n_requests` for the tied formats
only:

```python
report2 = ab_test(client, formats=[report.scores[0].format_id, *report.tied_with], n_requests=200)
```

A low `parse_strict` says the model is not answering in the protocol's shape. Look at a
few replies (`keep_records=True`) before you blame the format: the protocol changes
accuracy more than the format does (tab:protocol).

## From the command line

```bash
toolform ab-test --base-url http://localhost:8000/v1 --model Qwen/Qwen3-8B --no-thinking --out report.json
toolform ab-test --base-url http://localhost:8000/v1 --model Qwen/Qwen3-8B \
    --tools-file tools.json --examples examples.jsonl --rule symmetric
```

It first checks that the endpoint answers `GET /models` and exits 4 at once if not. It
shows a progress bar over the requests on a terminal, or a plain line every tenth of
the run in a log, then a table with each format's protocol, accuracy, Wilson interval,
strict parse rate, hallucinated share, mean prompt tokens, errors and replies cut off,
and the verdict: the winner and the formats tied with it, or "No difference measured",
or "Inconclusive" (exit 4). `--out` writes the report as JSON. For Qwen 3 and Qwen 3.5,
thinking is off unless you pass `--thinking`.

## Over HTTP

The API runs a measurement as a background job:

```bash
curl -s -X POST http://127.0.0.1:8765/api/v1/ab-test \
     -H 'content-type: application/json' \
     -d '{"model": "Qwen/Qwen3-8B", "n_requests": 50}'
# {"job_id": "3f2a...", "status": "queued", "total": 400, "warnings": ["thinking is off for this model, ..."]}
curl -s http://127.0.0.1:8765/api/v1/ab-test/3f2a...
curl -s -X DELETE http://127.0.0.1:8765/api/v1/ab-test/3f2a...      # cancel it
```

A job whose every request failed ends `failed`, with the error.

The server uses its own configured endpoint (`toolform serve --endpoint URL
--endpoint-model ID`); a `base_url` in the request is honoured only when the server
runs with `--allow-client-endpoints`. See [Deploy the API](deploy-the-api.md).

## What this costs

400 requests at the default settings, with `max_tokens=512` per reply. The study's
cost table gives the mean prompt and completion tokens per request for each core
format at 8 tools (tab:cost); `toolform evidence cost` prints it, and
`prompt_tokens_mean` in your report gives the real figure for your model and tools.
